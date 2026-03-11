"""Construction and road closure ingestion.

Pulls active closures from public DOT/WZDx GeoJSON feeds and the
511 SF Bay API (if a key is configured), buffers linestring geometries
to polygons, and persists them to the `closure_zones` PostGIS table.
"""

import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from geoalchemy2.elements import WKTElement
from shapely.geometry import LineString, mapping
from shapely.ops import unary_union
from sqlalchemy import delete
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.db import async_session_maker
from app.models.spatial import ClosureZone

logger = logging.getLogger(__name__)

# Public WZDx feed — California DOT (Caltrans)
CALTRANS_WZDX_URL = "https://cwwp2.dot.ca.gov/vm/feedprocessor/wzdx/d4/d4WZDxFeed.json"

# 511 SF Bay incidents endpoint (requires free API key)
BAY511_URL = "https://api.511.org/traffic/incidents?api_key={key}&format=json"

# Buffer radius in meters around a linestring closure
BUFFER_METERS = 50
# Approx degrees per meter at SF Bay latitude (~37.8°)
DEG_PER_METER = 1 / 111320


def _linestring_to_polygon_wkt(coords: list[list[float]], buffer_m: float = BUFFER_METERS) -> str | None:
    """Buffer a LineString by `buffer_m` meters and return WKT Polygon."""
    try:
        if len(coords) < 2:
            return None
        line = LineString([(c[0], c[1]) for c in coords])  # (lng, lat)
        buffered = line.buffer(buffer_m * DEG_PER_METER)
        return buffered.wkt
    except Exception as exc:
        logger.debug(f"Linestring buffer failed: {exc}")
        return None


def _point_to_polygon_wkt(lng: float, lat: float, radius_m: float = BUFFER_METERS) -> str:
    """Create a simple square polygon around a point."""
    d = radius_m * DEG_PER_METER
    return (
        f"POLYGON(({lng-d} {lat-d}, {lng+d} {lat-d}, "
        f"{lng+d} {lat+d}, {lng-d} {lat+d}, {lng-d} {lat-d}))"
    )


async def _fetch_wzdx() -> list[dict[str, Any]]:
    """Parse Caltrans WZDx GeoJSON feed into closure dicts."""
    closures = []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(CALTRANS_WZDX_URL)
            resp.raise_for_status()
            data = resp.json()
        for feature in data.get("features", []):
            props = feature.get("properties", {})
            geom = feature.get("geometry", {})
            coords = geom.get("coordinates", [])
            geom_type = geom.get("type", "")

            wkt = None
            if geom_type == "LineString":
                wkt = _linestring_to_polygon_wkt(coords)
            elif geom_type == "Point" and len(coords) >= 2:
                wkt = _point_to_polygon_wkt(coords[0], coords[1])

            if not wkt:
                continue

            start_str = props.get("start_date") or props.get("beginning_cross_street")
            end_str = props.get("end_date")

            closures.append({
                "source": "wzdx_caltrans",
                "closure_type": props.get("event_type", "construction"),
                "description": props.get("road_name", "") + " — " + props.get("description", ""),
                "wkt": wkt,
                "start_time": _parse_dt(start_str),
                "end_time": _parse_dt(end_str),
            })
    except Exception as exc:
        logger.warning(f"WZDx fetch failed: {exc}")
    return closures


async def _fetch_511sf() -> list[dict[str, Any]]:
    """Parse 511 SF Bay incidents into closure dicts. Requires API key."""
    if not settings.bay511_api_key:
        return []
    closures = []
    try:
        url = BAY511_URL.format(key=settings.bay511_api_key)
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
        for event in data.get("events", []):
            coords = event.get("geography", {}).get("coordinates", [])
            geom_type = event.get("geography", {}).get("type", "")
            wkt = None
            if geom_type == "Point" and len(coords) >= 2:
                wkt = _point_to_polygon_wkt(coords[0], coords[1])
            elif geom_type == "LineString":
                wkt = _linestring_to_polygon_wkt(coords)
            if not wkt:
                continue
            closures.append({
                "source": "511sf",
                "closure_type": event.get("event_type", "incident"),
                "description": event.get("headline", ""),
                "wkt": wkt,
                "start_time": _parse_dt(event.get("created")),
                "end_time": _parse_dt(event.get("updated")),
            })
    except Exception as exc:
        logger.warning(f"511 SF Bay fetch failed: {exc}")
    return closures


def _parse_dt(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            return datetime.strptime(value[:19], fmt[:len(value[:19])])
        except ValueError:
            continue
    return None


async def refresh_closure_zones() -> int:
    """Fetch, buffer, and persist closure zones to PostGIS.

    Returns:
        Number of closure zones written to the database.
    """
    logger.info("Refreshing closure zones...")

    all_closures = await _fetch_wzdx()
    all_closures += await _fetch_511sf()

    if not all_closures:
        logger.info("No closure zones found from any source.")
        return 0

    try:
        async with async_session_maker() as session:
            # Replace all previously ingested closures from automated sources
            await session.execute(
                delete(ClosureZone).where(
                    ClosureZone.source.in_(["wzdx_caltrans", "511sf"])
                )
            )
            for c in all_closures:
                zone = ClosureZone(
                    source=c["source"],
                    closure_type=c["closure_type"],
                    description=c["description"][:500] if c["description"] else None,
                    geom=WKTElement(c["wkt"], srid=4326),
                    start_time=c["start_time"],
                    end_time=c["end_time"],
                )
                session.add(zone)
            await session.commit()

        logger.info(f"Persisted {len(all_closures)} closure zones to PostGIS.")
        return len(all_closures)

    except SQLAlchemyError as exc:
        logger.error(f"Database error while persisting closure zones: {exc}")
        return 0
