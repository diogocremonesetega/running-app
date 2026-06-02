"""Spatial helpers for route generation (OSM peaks for hilly mode)."""

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_OVERPASS_URL = "https://overpass-api.de/api/interpreter"


async def find_highest_peak_near(
    lat: float,
    lng: float,
    radius_m: float = 3000,
) -> Optional[dict]:
    """Query OSM for the highest natural peak or viewpoint within radius_m."""
    query = (
        f"[out:json][timeout:10];\n"
        f"(\n"
        f'  node["natural"="peak"](around:{int(radius_m)},{lat},{lng});\n'
        f'  node["tourism"="viewpoint"](around:{int(radius_m)},{lat},{lng});\n'
        f'  node["natural"="hill"](around:{int(radius_m)},{lat},{lng});\n'
        f");\nout body;"
    )
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                _OVERPASS_URL,
                data={"data": query},
                headers={"User-Agent": "RunningRouteGenerator/1.0"},
            )
        if resp.status_code != 200:
            logger.warning("Overpass peak query returned %s", resp.status_code)
            return None

        elements = resp.json().get("elements", [])
        if not elements:
            return None

        best = None
        best_ele = -999.0
        for el in elements:
            tags = el.get("tags", {})
            raw_ele = tags.get("ele", None)
            try:
                ele = float(raw_ele) if raw_ele else 0.0
            except ValueError:
                ele = 0.0
            if ele > best_ele:
                best_ele = ele
                best = {
                    "lat": el["lat"],
                    "lng": el["lon"],
                    "ele": ele,
                    "name": tags.get("name", "Peak"),
                }

        return best

    except Exception as exc:
        logger.warning("Overpass peak query failed: %s", exc)
        return None
