"""Diagnostic endpoint — GraphHopper and database connectivity."""

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
    start = time.monotonic()
    try:
        async with async_session_maker() as session:
            result = await session.execute(text("SELECT 1"))
            val = result.scalar()
        elapsed = round(time.monotonic() - start, 2)

        postgis = False
        try:
            async with async_session_maker() as session:
                await session.execute(text("SELECT PostGIS_Version()"))
                postgis = True
        except Exception:
            pass

        route_history_count = None
        try:
            async with async_session_maker() as session:
                r = await session.execute(text("SELECT COUNT(*) FROM route_history"))
                route_history_count = r.scalar()
        except Exception:
            route_history_count = "table not found"

        return {
            "service": "PostgreSQL",
            "status": "ok" if val == 1 else "degraded",
            "latency_s": elapsed,
            "postgis_enabled": postgis,
            "route_history_count": route_history_count,
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
    """Ping GraphHopper and the database."""
    checks = [
        _check_url(
            "GraphHopper",
            f"{settings.graphhopper_url}/route",
            params={
                "point": "37.87,-122.26",
                "profile": "foot",
                "points_encoded": "false",
                **({"key": settings.graphhopper_api_key} if settings.graphhopper_api_key else {}),
            },
        ),
    ]

    api_results = await asyncio.gather(*checks, return_exceptions=True)
    db_result = await _check_database()

    cleaned = []
    for r in api_results:
        if isinstance(r, Exception):
            cleaned.append({"service": "unknown", "status": "error", "error": str(r)})
        else:
            cleaned.append(r)

    all_ok = all(r.get("status") == "ok" for r in cleaned) and db_result.get("status") == "ok"

    return {
        "overall": "healthy" if all_ok else "issues_detected",
        "apis": cleaned,
        "database": db_result,
    }
