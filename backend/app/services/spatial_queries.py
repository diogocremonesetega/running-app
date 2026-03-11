"""Reusable PostGIS spatial queries for route generation."""

import logging
from datetime import datetime, timezone

from geoalchemy2.elements import WKTElement
from geoalchemy2.functions import ST_AsGeoJSON
from sqlalchemy import select, and_
from sqlalchemy.exc import SQLAlchemyError

from app.db import async_session_maker
from app.models.spatial import SafetyZone, ClosureZone, ScenicSegment

logger = logging.getLogger(__name__)

# Approximate degrees per meter at ~37° latitude
DEG_PER_M = 1 / 111320


async def get_active_safety_zones(lat: float, lng: float, radius_m: float = 5000) -> list[dict]:
    """Return safety zones within radius of a point.

    Each result is shaped for direct injection into GraphHopper `areas`.

    Returns:
        List of dicts: {id, safety_score, geojson_geom}
    """
    try:
        async with async_session_maker() as session:
            point = WKTElement(f"POINT({lng} {lat})", srid=4326)
            result = await session.execute(
                select(
                    SafetyZone.id,
                    SafetyZone.safety_score,
                    SafetyZone.source,
                    ST_AsGeoJSON(SafetyZone.geom).label("geojson"),
                ).where(
                    and_(
                        SafetyZone.geom.ST_DWithin(point, radius_m * DEG_PER_M),
                        SafetyZone.expires_at > datetime.now(timezone.utc),
                    )
                )
            )
            rows = result.mappings().all()
            return [
                {
                    "id": f"safety_zone_{r['id']}",
                    "safety_score": r["safety_score"],
                    "source": r["source"],
                    "geojson": r["geojson"],
                }
                for r in rows
            ]
    except SQLAlchemyError as exc:
        logger.error(f"Error querying safety zones: {exc}")
        return []


async def get_active_closures(lat: float, lng: float, radius_m: float = 5000) -> list[dict]:
    """Return active construction/closure zones within radius.

    Filters out zones whose `end_time` is in the past.

    Returns:
        List of dicts: {id, closure_type, description, geojson_geom}
    """
    try:
        now = datetime.now(timezone.utc)
        async with async_session_maker() as session:
            point = WKTElement(f"POINT({lng} {lat})", srid=4326)
            result = await session.execute(
                select(
                    ClosureZone.id,
                    ClosureZone.closure_type,
                    ClosureZone.description,
                    ClosureZone.source,
                    ST_AsGeoJSON(ClosureZone.geom).label("geojson"),
                ).where(
                    and_(
                        ClosureZone.geom.ST_DWithin(point, radius_m * DEG_PER_M),
                        # Include closures with no end_time OR where end_time > now
                        (ClosureZone.end_time == None) | (ClosureZone.end_time > now),
                    )
                )
            )
            rows = result.mappings().all()
            return [
                {
                    "id": f"closure_zone_{r['id']}",
                    "closure_type": r["closure_type"],
                    "description": r["description"],
                    "source": r["source"],
                    "geojson": r["geojson"],
                }
                for r in rows
            ]
    except SQLAlchemyError as exc:
        logger.error(f"Error querying closure zones: {exc}")
        return []


async def get_scenic_segments_near(lat: float, lng: float, radius_m: float = 3000,
                                    min_score: float = 0.7) -> list[dict]:
    """Return scenic segments within radius, filtered by minimum GVI score.

    Returns:
        List of dicts: {id, gvi_score, park_coverage, geojson}
    """
    try:
        async with async_session_maker() as session:
            point = WKTElement(f"POINT({lng} {lat})", srid=4326)
            result = await session.execute(
                select(
                    ScenicSegment.id,
                    ScenicSegment.gvi_score,
                    ScenicSegment.park_coverage,
                    ST_AsGeoJSON(ScenicSegment.geom).label("geojson"),
                ).where(
                    and_(
                        ScenicSegment.geom.ST_DWithin(point, radius_m * DEG_PER_M),
                        ScenicSegment.gvi_score >= min_score,
                    )
                )
            )
            rows = result.mappings().all()
            return [
                {
                    "id": f"scenic_{r['id']}",
                    "gvi_score": r["gvi_score"],
                    "park_coverage": r["park_coverage"],
                    "geojson": r["geojson"],
                }
                for r in rows
            ]
    except SQLAlchemyError as exc:
        logger.error(f"Error querying scenic segments: {exc}")
        return []


logger = logging.getLogger(__name__)

# Approximate degrees per meter at ~37° latitude
DEG_PER_M = 1 / 111320


async def get_active_safety_zones(lat: float, lng: float, radius_m: float = 5000) -> list[dict]:
    """Return safety zones within radius of a point.

    Each result is shaped for direct injection into GraphHopper `areas`.

    Returns:
        List of dicts: {id, safety_score, geojson_geom}
    """
    try:
        async with async_session_maker() as session:
            point = WKTElement(f"POINT({lng} {lat})", srid=4326)
            result = await session.execute(
                select(
                    SafetyZone.id,
                    SafetyZone.safety_score,
                    SafetyZone.source,
                    ST_AsGeoJSON(SafetyZone.geom).label("geojson"),
                ).where(
                    and_(
                        SafetyZone.geom.ST_DWithin(point, radius_m * DEG_PER_M),
                        SafetyZone.expires_at > datetime.now(timezone.utc),
                    )
                )
            )
            rows = result.mappings().all()
            return [
                {
                    "id": f"safety_zone_{r['id']}",
                    "safety_score": r["safety_score"],
                    "source": r["source"],
                    "geojson": r["geojson"],
                }
                for r in rows
            ]
    except SQLAlchemyError as exc:
        logger.error(f"Error querying safety zones: {exc}")
        return []


async def get_active_closures(lat: float, lng: float, radius_m: float = 5000) -> list[dict]:
    """Return active construction/closure zones within radius.

    Filters out zones whose `end_time` is in the past.

    Returns:
        List of dicts: {id, closure_type, description, geojson_geom}
    """
    try:
        now = datetime.now(timezone.utc)
        async with async_session_maker() as session:
            point = WKTElement(f"POINT({lng} {lat})", srid=4326)
            result = await session.execute(
                select(
                    ClosureZone.id,
                    ClosureZone.closure_type,
                    ClosureZone.description,
                    ClosureZone.source,
                    ST_AsGeoJSON(ClosureZone.geom).label("geojson"),
                ).where(
                    and_(
                        ClosureZone.geom.ST_DWithin(point, radius_m * DEG_PER_M),
                        # Include closures with no end_time OR where end_time > now
                        (ClosureZone.end_time == None) | (ClosureZone.end_time > now),
                    )
                )
            )
            rows = result.mappings().all()
            return [
                {
                    "id": f"closure_zone_{r['id']}",
                    "closure_type": r["closure_type"],
                    "description": r["description"],
                    "source": r["source"],
                    "geojson": r["geojson"],
                }
                for r in rows
            ]
    except SQLAlchemyError as exc:
        logger.error(f"Error querying closure zones: {exc}")
        return []
