"""Scenic segment ingestion from OpenStreetMap.

Queries the Overpass API for parks, trails, and waterways within a
bounding box, scores each segment by scenic quality (GVI proxy), and
persists them to the `scenic_segments` PostGIS table.
"""

import logging
from typing import Any

import httpx
from geoalchemy2.elements import WKTElement
from sqlalchemy import delete
from sqlalchemy.exc import SQLAlchemyError

from app.db import async_session_maker
from app.models.spatial import ScenicSegment

logger = logging.getLogger(__name__)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Approximate degrees per meter at Bay Area latitude
DEG_PER_M = 1 / 111320

# Default bounding box: Berkeley + surrounding area (south,west,north,east)
DEFAULT_BBOX = "37.82,-122.32,37.92,-122.22"

# GVI-proxy scores by feature type
_SCORES: dict[str, float] = {
    "park": 1.0,
    "trail": 0.9,
    "waterway": 0.7,
    "nature": 0.85,
}


def _build_overpass_query(bbox: str) -> str:
    return f"""
[out:json][timeout:25];
(
  way["leisure"="park"]({bbox});
  way["highway"~"^(path|track|footway)$"]["surface"!="asphalt"]({bbox});
  way["natural"~"^(wood|scrub|heath)$"]({bbox});
  way["waterway"~"^(river|stream|canal)$"]({bbox});
);
out geom;
"""


def _feature_score(tags: dict) -> float:
    if tags.get("leisure") == "park" or tags.get("natural") in ("wood", "scrub", "heath"):
        return _SCORES["park"]
    hw = tags.get("highway", "")
    if hw in ("path", "track", "footway"):
        return _SCORES["trail"]
    if tags.get("waterway"):
        return _SCORES["waterway"]
    return 0.6


def _nodes_to_wkt(geometry: list[dict]) -> str | None:
    """Convert a list of {lat, lon} node dicts to a 2D WKT LINESTRING.

    Coordinate pairs must be comma-separated: LINESTRING(lng lat, lng lat, ...)
    """
    if len(geometry) < 2:
        return None
    # Each point is "lng lat" — pairs separated by commas
    coords = ", ".join(f"{pt['lon']} {pt['lat']}" for pt in geometry)
    return f"LINESTRING({coords})"


async def refresh_scenic_segments(bbox: str = DEFAULT_BBOX) -> int:
    """Fetch and persist scenic segments from OSM to PostGIS.

    Args:
        bbox: Overpass bounding box string "south,west,north,east"

    Returns:
        Number of segments written.
    """
    logger.info(f"Refreshing scenic segments for bbox={bbox}...")
    query = _build_overpass_query(bbox)

    try:
        headers = {"User-Agent": "RunningRouteGenerator/1.0 (Contact: admin@example.com)"}
        async with httpx.AsyncClient(timeout=60.0, headers=headers) as client:
            resp = await client.post(OVERPASS_URL, data=query)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        logger.warning(f"Overpass API rejected the request ({exc.response.status_code}). Scenic data will be stale.")
        return 0
    except httpx.TimeoutException:
        logger.warning("Overpass API timed out. Scenic data will be stale.")
        return 0
    except Exception as exc:
        logger.error(f"OSM Overpass fetch failed: {exc}")
        return 0

    elements = data.get("elements", [])
    segments: list[dict[str, Any]] = []

    for el in elements:
        geometry = el.get("geometry", [])
        wkt = _nodes_to_wkt(geometry)
        if not wkt:
            continue
        tags = el.get("tags", {})
        score = _feature_score(tags)
        # Park coverage: 1.0 if it's a park/nature area, else 0
        park_coverage = 1.0 if tags.get("leisure") == "park" or tags.get("natural") else 0.0
        segments.append({"wkt": wkt, "gvi_score": score, "park_coverage": park_coverage})

    if not segments:
        logger.info("No scenic segments found.")
        return 0

    try:
        async with async_session_maker() as session:
            # Replace all OSM scenic data on each refresh
            await session.execute(delete(ScenicSegment))
            for s in segments:
                seg = ScenicSegment(
                    gvi_score=s["gvi_score"],
                    park_coverage=s["park_coverage"],
                    geom=WKTElement(s["wkt"], srid=4326),
                )
                session.add(seg)
            await session.commit()

        logger.info(f"Persisted {len(segments)} scenic segments to PostGIS.")
        return len(segments)

    except SQLAlchemyError as exc:
        logger.error(f"Database error persisting scenic segments: {exc}")
        return 0
