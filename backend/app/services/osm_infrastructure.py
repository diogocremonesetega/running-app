"""OpenStreetMap Overpass queries for route infrastructure toggles."""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_OVERPASS_URL = "https://overpass-api.de/api/interpreter"


async def _overpass_post(query: str, timeout: float = 60.0) -> list[dict[str, Any]]:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(_OVERPASS_URL, data={"data": query})
            resp.raise_for_status()
            return resp.json().get("elements", [])
    except Exception as exc:
        logger.warning("Overpass query failed: %s", exc)
        return []


def _bounds_boxes(elements: list[dict[str, Any]]) -> list[dict[str, float]]:
    zones: list[dict[str, float]] = []
    for el in elements:
        bounds = el.get("bounds")
        if bounds:
            zones.append({
                "min_lat": bounds["minlat"],
                "max_lat": bounds["maxlat"],
                "min_lng": bounds["minlon"],
                "max_lng": bounds["maxlon"],
            })
            continue
        lat = el.get("lat")
        lng = el.get("lon")
        if lat is not None and lng is not None:
            pad = 0.00015
            zones.append({
                "min_lat": lat - pad,
                "max_lat": lat + pad,
                "min_lng": lng - pad,
                "max_lng": lng + pad,
            })
    return zones


async def fetch_unlit_street_boxes(bbox: str) -> list[dict[str, float]]:
    """Unlit highway segments as bounding boxes (south,west,north,east bbox string)."""
    query = f"""
    [out:json][timeout:15];
    way["highway"]["lit"="no"]({bbox});
    out bb;
    """
    elements = await _overpass_post(query)
    return _bounds_boxes(elements)


async def fetch_water_points(bbox: str) -> list[dict[str, float]]:
    """Hydration amenities: drinking_water, water_point, fountains with potable water."""
    query = f"""
    [out:json][timeout:15];
    (
      node["amenity"="drinking_water"]({bbox});
      node["amenity"="water_point"]({bbox});
      node["amenity"="fountain"]["drinking_water"!="no"]({bbox});
      way["amenity"="drinking_water"]({bbox});
      way["amenity"="water_point"]({bbox});
    );
    out center bb;
    """
    elements = await _overpass_post(query)
    return _bounds_boxes(elements)


async def fetch_restroom_points(bbox: str) -> list[dict[str, float]]:
    """Public restroom amenities."""
    query = f"""
    [out:json][timeout:15];
    (
      node["amenity"="toilets"]({bbox});
      node["amenity"="public_bathrooms"]({bbox});
      node["toilets"="yes"]({bbox});
      way["amenity"="toilets"]({bbox});
      way["amenity"="public_bathrooms"]({bbox});
    );
    out center bb;
    """
    elements = await _overpass_post(query)
    return _bounds_boxes(elements)
