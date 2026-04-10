"""Crime data ingestion with PostGIS persistence.

Fetches crime incidents from the Berkeley and San Francisco Socrata open data APIs,
grids them into ~150m cells, computes a Safety Quality Index (SQI)
per cell, and persists low-SQI zones to the `safety_zones` PostGIS table.
"""

import logging
import math
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from geoalchemy2.elements import WKTElement
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError

from app.db import async_session_maker
from app.models.spatial import SafetyZone

logger = logging.getLogger(__name__)

# Socrata open data endpoints
BERKELEY_SOCRATA_URL = "https://data.cityofberkeley.info/resource/k2nh-s5h5.json?$limit=1000&$order=eventdt DESC"
SF_SOCRATA_URL = "https://data.sfgov.org/resource/wg3w-h783.json?$where=latitude IS NOT NULL&$limit=1500&$order=incident_datetime DESC"

# ~150m grid cell size in degrees (at Berkeley latitude)
CELL_SIZE_DEG = 0.0013

# SQI threshold below which a cell is flagged as unsafe
SQI_UNSAFE_THRESHOLD = 99

# TTL for persisted safety zones
ZONE_TTL_HOURS = 24


# --- Severity weights by crime category ---
_SEVERITY: dict[str, float] = {
    "ROBBERY": 1.0,
    "ASSAULT": 1.0,
    "WEAPON": 1.0,
    "BURGLARY": 0.8,
    "THEFT": 0.7,
    "LARCENY": 0.7,
    "VANDALISM": 0.5,
}


def _incident_weight(cvlegend: str) -> float:
    upper = cvlegend.upper()
    for key, w in _SEVERITY.items():
        if key in upper:
            return w
    return 0.3


def _cell_key(lat: float, lng: float) -> tuple[float, float]:
    """Snap a coordinate to the nearest grid cell origin."""
    return (
        math.floor(lat / CELL_SIZE_DEG) * CELL_SIZE_DEG,
        math.floor(lng / CELL_SIZE_DEG) * CELL_SIZE_DEG,
    )


def _cell_to_wkt(cell_lat: float, cell_lng: float) -> str:
    """Convert a grid cell origin to a WKT Polygon string."""
    min_lat, min_lng = cell_lat, cell_lng
    max_lat = min_lat + CELL_SIZE_DEG
    max_lng = min_lng + CELL_SIZE_DEG
    return (
        f"POLYGON(("
        f"{min_lng} {min_lat}, {max_lng} {min_lat}, "
        f"{max_lng} {max_lat}, {min_lng} {max_lat}, "
        f"{min_lng} {min_lat}))"
    )


async def _fetch_incidents(url: str) -> list[dict[str, Any]]:
    """Fetch raw incidents from Socrata API."""
    headers = {"User-Agent": "RunningRouteGenerator/1.0 (Contact: admin@example.com)"}
    async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


def _grid_incidents(raw: list[dict[str, Any]]) -> dict[tuple, float]:
    """Grid incidents and accumulate weighted counts per cell.

    Returns:
        Dict mapping (cell_lat, cell_lng) → total_weight
    """
    cells: dict[tuple, float] = {}
    for row in raw:
        loc = row.get("block_location", {})
        try:
            lat = float(loc.get("latitude") or row.get("latitude") or 0)
            lng = float(loc.get("longitude") or row.get("longitude") or 0)
        except (TypeError, ValueError):
            continue
        if not lat or not lng:
            continue
        
        category = row.get("cvlegend", "") or row.get("incident_category", "")
        weight = _incident_weight(category)
        key = _cell_key(lat, lng)
        cells[key] = cells.get(key, 0.0) + weight
    return cells


def _compute_sqi(cells: dict[tuple, float]) -> dict[tuple, float]:
    """Compute SQI (0-100) per cell. Lower = more dangerous."""
    if not cells:
        return {}
    max_weight = max(cells.values())
    return {
        cell: round(100 - (weight / max_weight * 100), 1)
        for cell, weight in cells.items()
    }


async def refresh_safety_zones() -> int:
    """Main entry point: fetch, grid, score, and persist to PostGIS.

    Returns:
        Number of unsafe zones written to the database.
    """
    logger.info("Refreshing safety zones from Bay Area crime data...")
    raw = []
    
    try:
        berkeley_raw = await _fetch_incidents(BERKELEY_SOCRATA_URL)
        raw.extend(berkeley_raw)
    except httpx.HTTPStatusError as exc:
        logger.warning(f"Berkeley API rejected the request ({exc.response.status_code}).")
    except Exception as exc:
        logger.error(f"Failed to fetch Berkeley crime incidents: {exc}")

    try:
        sf_raw = await _fetch_incidents(SF_SOCRATA_URL)
        raw.extend(sf_raw)
    except httpx.HTTPStatusError as exc:
        logger.warning(f"SF API rejected the request ({exc.response.status_code}).")
    except Exception as exc:
        logger.error(f"Failed to fetch SF crime incidents: {exc}")

    if not raw:
        logger.warning("Both safety APIs failed. Skipping zone refresh.")
        return 0

    cells = _grid_incidents(raw)
    sqi_map = _compute_sqi(cells)
    unsafe_cells = {cell: sqi for cell, sqi in sqi_map.items() if sqi < SQI_UNSAFE_THRESHOLD}

    if not unsafe_cells:
        logger.info("No unsafe cells found.")
        return 0

    expires_at = datetime.now(timezone.utc) + timedelta(hours=ZONE_TTL_HOURS)

    try:
        async with async_session_maker() as session:
            # Purge existing non-expired zones from this source to avoid stale duplicates
            await session.execute(
                delete(SafetyZone).where(SafetyZone.source == "bay_area_socrata")
            )
            for (cell_lat, cell_lng), sqi in unsafe_cells.items():
                wkt = _cell_to_wkt(cell_lat, cell_lng)
                zone = SafetyZone(
                    source="bay_area_socrata",
                    safety_score=sqi,
                    geom=WKTElement(wkt, srid=4326),
                    expires_at=expires_at,
                )
                session.add(zone)
            await session.commit()

        logger.info(f"Persisted {len(unsafe_cells)} unsafe safety zones to PostGIS.")
        return len(unsafe_cells)

    except SQLAlchemyError as exc:
        logger.error(f"Database error while persisting safety zones: {exc}")
        return 0


async def get_zone_geojson_polygons(lat: float, lng: float, radius_m: float = 5000) -> list[dict]:
    """Query PostGIS for active safety zones near a location.

    Returns a list of dicts shaped for GraphHopper `areas` injection:
        [{'id': 'safety_zone_1', 'wkt': 'POLYGON(...)', 'score': 30.0}, ...]
    """
    try:
        async with async_session_maker() as session:
            # Build a point WKT for ST_DWithin
            point_wkt = f"SRID=4326;POINT({lng} {lat})"
            result = await session.execute(
                select(SafetyZone).where(
                    SafetyZone.geom.ST_DWithin(
                        WKTElement(f"POINT({lng} {lat})", srid=4326),
                        radius_m / 111320,  # convert meters to approximate degrees
                    ),
                    SafetyZone.expires_at > datetime.now(timezone.utc),
                )
            )
            zones = result.scalars().all()
            return [
                {
                    "id": f"safety_zone_{z.id}",
                    "score": z.safety_score,
                    "source": z.source,
                }
                for z in zones
            ]
    except SQLAlchemyError as exc:
        logger.error(f"Error querying safety zones: {exc}")
        return []
