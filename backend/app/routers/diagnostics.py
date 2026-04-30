"""Diagnostic endpoint — validates connectivity to all external APIs and the database."""

import asyncio
import logging
import time
from typing import Any

import httpx
from fastapi import APIRouter
from sqlalchemy import text

from app.config import settings
from app.db import async_session_maker

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["diagnostics"])


async def _check_url(name: str, url: str, method: str = "GET", timeout: float = 8.0, **kwargs) -> dict[str, Any]:
    """Ping a URL and return status."""
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            if method == "POST":
                resp = await client.post(url, **kwargs)
            else:
                resp = await client.get(url, **kwargs)
        elapsed = round(time.monotonic() - start, 2)
        return {
            "service": name,
            "status": "ok" if resp.status_code == 200 else "degraded",
            "http_code": resp.status_code,
            "latency_s": elapsed,
        }
    except httpx.TimeoutException:
        return {"service": name, "status": "timeout", "latency_s": round(time.monotonic() - start, 2)}
    except Exception as exc:
        return {"service": name, "status": "error", "error": f"{type(exc).__name__}: {exc}"}


async def _check_database() -> dict[str, Any]:
    """Attempt a simple SQL query against the configured database."""
    start = time.monotonic()
    try:
        async with async_session_maker() as session:
            result = await session.execute(text("SELECT 1"))
            val = result.scalar()
        elapsed = round(time.monotonic() - start, 2)

        # Also check for PostGIS
        postgis = False
        try:
            async with async_session_maker() as session:
                await session.execute(text("SELECT PostGIS_Version()"))
                postgis = True
        except Exception:
            pass

        # Count rows in spatial tables
        counts = {}
        for table in ["safety_zones", "closure_zones", "scenic_segments"]:
            try:
                async with async_session_maker() as session:
                    r = await session.execute(text(f"SELECT COUNT(*) FROM {table}"))
                    counts[table] = r.scalar()
            except Exception:
                counts[table] = "table not found"

        return {
            "service": "PostgreSQL",
            "status": "ok" if val == 1 else "degraded",
            "latency_s": elapsed,
            "postgis_enabled": postgis,
            "table_row_counts": counts,
            "database_url_host": settings.database_url.split("@")[-1].split("/")[0] if settings.database_url else "not set",
        }
    except Exception as exc:
        return {
            "service": "PostgreSQL",
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "latency_s": round(time.monotonic() - start, 2),
        }


@router.get("/diagnostics")
async def run_diagnostics():
    """Ping every external API and the database. Returns a status report."""

    # Build the list of checks
    checks = [
        _check_url(
            "GraphHopper",
            f"{settings.graphhopper_url}/route",
            params={"point": "37.87,-122.26", "profile": "foot", "points_encoded": "false",
                     **({"key": settings.graphhopper_api_key} if settings.graphhopper_api_key else {})},
        ),
        _check_url(
            "Open-Meteo Weather",
            "https://api.open-meteo.com/v1/forecast?latitude=37.87&longitude=-122.26&current=temperature_2m",
        ),
        _check_url(
            "Open-Meteo AQI",
            "https://air-quality-api.open-meteo.com/v1/air-quality?latitude=37.87&longitude=-122.26&current=us_aqi",
        ),
        _check_url(
            "Overpass (OSM)",
            "https://overpass-api.de/api/interpreter",
            method="POST",
            data={"data": '[out:json][timeout:5];node["natural"="peak"](around:1000,37.87,-122.26);out 1;'},
        ),
        _check_url(
            "Caltrans WZDx",
            "https://cwwp2.dot.ca.gov/vm/feedprocessor/wzdx/d4/d4WZDxFeed.json",
        ),
        _check_url(
            "Berkeley Socrata (Crime)",
            "https://data.cityofberkeley.info/resource/k2nh-s5h5.json?$limit=1",
        ),
        _check_url(
            "SF Socrata (Crime)",
            "https://data.sfgov.org/resource/wg3w-h783.json?$limit=1",
        ),
    ]

    # 511 only if key is configured
    if settings.bay511_api_key:
        checks.append(_check_url(
            "511 SF Bay",
            f"https://api.511.org/traffic/incidents?api_key={settings.bay511_api_key}&format=json",
        ))

    skip_511 = not settings.bay511_api_key

    # Run all API checks in parallel, then check database
    api_results = await asyncio.gather(*checks, return_exceptions=True)
    db_result = await _check_database()

    # Clean up any exceptions from gather
    cleaned = []
    for r in api_results:
        if isinstance(r, Exception):
            cleaned.append({"service": "unknown", "status": "error", "error": str(r)})
        else:
            cleaned.append(r)

    if skip_511:
        cleaned.append({"service": "511 SF Bay", "status": "skipped", "reason": "BAY511_API_KEY not set"})

    all_ok = all(r.get("status") == "ok" for r in cleaned) and db_result.get("status") == "ok"

    return {
        "overall": "healthy" if all_ok else "issues_detected",
        "apis": cleaned,
        "database": db_result,
    }
