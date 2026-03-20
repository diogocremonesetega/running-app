"""GraphHopper HTTP client service.

Wraps the self-hosted GraphHopper /route endpoint, supporting both
simple GET requests and POST requests with custom model overrides.
"""

from __future__ import annotations

import httpx
from typing import Any

from app.config import settings


class GraphHopperError(Exception):
    """Raised when GraphHopper returns an error response."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"GraphHopper error {status_code}: {detail}")


async def health_check() -> dict:
    """Check if GraphHopper is running and healthy.

    Returns a graceful 'unavailable' status instead of crashing if
    GraphHopper has not yet started (e.g., still indexing the OSM graph).
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.graphhopper_url}/health")
        return {"status": "ok" if resp.status_code == 200 else "degraded", "code": resp.status_code}
    except Exception:
        return {"status": "unavailable", "code": None, "note": "GraphHopper not reachable — may still be indexing"}


async def get_route(
    waypoints: list[tuple[float, float]],
    profile: str = "foot_elevation",
    elevation: bool = True,
    details: list[str] | None = None,
    alternative_routes: int = 0,
) -> dict[str, Any]:
    """Fetch a route from GraphHopper using a GET request.

    Args:
        waypoints: List of (lat, lng) tuples defining the route.
        profile: GraphHopper profile name.
        elevation: Include 3D coordinates.
        details: Extra edge details to include (e.g., ["average_slope"]).
        alternative_routes: Number of alternative routes (0 = disabled).

    Returns:
        Parsed JSON response from GraphHopper.
    """
    if details is None:
        details = ["average_slope"]

    params: list[tuple[str, str]] = []

    # Multiple point params for waypoints
    for lat, lng in waypoints:
        params.append(("point", f"{lat},{lng}"))

    params.append(("profile", profile))
    params.append(("elevation", str(elevation).lower()))
    params.append(("points_encoded", "false"))
    params.append(("ch.disable", "true"))
    params.append(("instructions", "true"))
    params.append(("calc_points", "true"))

    for d in details:
        params.append(("details", d))

    if alternative_routes > 1:
        params.append(("algorithm", "alternative_route"))
        params.append(("alternative_route.max_paths", str(alternative_routes)))

    if settings.graphhopper_api_key:
        params.append(("key", settings.graphhopper_api_key))

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(f"{settings.graphhopper_url}/route", params=params)

    if resp.status_code != 200:
        raise GraphHopperError(resp.status_code, resp.text)

    return resp.json()


async def post_route_with_custom_model(
    waypoints: list[tuple[float, float]],
    profile: str = "foot_elevation",
    custom_model: dict[str, Any] | None = None,
    elevation: bool = True,
    details: list[str] | None = None,
) -> dict[str, Any]:
    """Fetch a route using POST with a dynamic custom model override.

    This allows injecting per-request priority/speed rules and geographic
    area penalties (e.g., crime zones, construction zones) without
    rebuilding the routing graph.

    Args:
        waypoints: List of (lat, lng) tuples.
        profile: Base profile name.
        custom_model: JSON custom model with speed/priority/areas overrides.
        elevation: Include 3D coordinates.
        details: Extra edge details.

    Returns:
        Parsed JSON response from GraphHopper.
    """
    if details is None:
        details = ["average_slope"]

    body: dict[str, Any] = {
        "points": [[lng, lat] for lat, lng in waypoints],  # GH POST uses [lng, lat]
        "profile": profile,
        "elevation": elevation,
        "points_encoded": False,
        "ch.disable": True,
        "instructions": True,
        "calc_points": True,
        "details": details,
    }

    if custom_model:
        body["custom_model"] = custom_model

    params = {}
    if settings.graphhopper_api_key:
        params["key"] = settings.graphhopper_api_key

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{settings.graphhopper_url}/route",
            json=body,
            params=params,
        )

    if resp.status_code != 200:
        raise GraphHopperError(resp.status_code, resp.text)

    return resp.json()


def extract_elevation_profile(path_data: dict) -> list[dict]:
    """Extract elevation profile data from a GraphHopper path response.

    Returns a list of points with cumulative distance and elevation,
    suitable for charting.

    Args:
        path_data: A single path from GraphHopper's paths[] array.

    Returns:
        List of dicts with keys: distance_m, elevation_m, lat, lng
    """
    coordinates = path_data.get("points", {}).get("coordinates", [])
    if not coordinates:
        return []

    profile_points = []
    cumulative_distance = 0.0

    for i, coord in enumerate(coordinates):
        lng, lat = coord[0], coord[1]
        elevation = coord[2] if len(coord) > 2 else 0.0

        if i > 0:
            prev = coordinates[i - 1]
            cumulative_distance += _haversine(prev[1], prev[0], lat, lng)

        profile_points.append({
            "index": i,
            "distance_m": round(cumulative_distance, 1),
            "elevation_m": round(elevation, 1),
            "lat": lat,
            "lng": lng,
        })

    return profile_points


def extract_slope_segments(path_data: dict) -> list[dict]:
    """Extract slope segment data from GraphHopper details.

    Returns segments with start/end distances and slope values for
    color-coding the route by gradient.
    """
    slope_details = path_data.get("details", {}).get("average_slope", [])
    coordinates = path_data.get("points", {}).get("coordinates", [])

    if not slope_details or not coordinates:
        return []

    # Pre-compute cumulative distances
    distances = [0.0]
    for i in range(1, len(coordinates)):
        prev = coordinates[i - 1]
        curr = coordinates[i]
        d = _haversine(prev[1], prev[0], curr[1], curr[0])
        distances.append(distances[-1] + d)

    segments = []
    for from_idx, to_idx, slope in slope_details:
        segments.append({
            "from_index": from_idx,
            "to_index": to_idx,
            "from_distance_m": round(distances[from_idx], 1),
            "to_distance_m": round(distances[min(to_idx, len(distances) - 1)], 1),
            "slope_percent": round(slope, 2),
        })

    return segments


import math


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in meters between two GPS coordinates."""
    R = 6_371_000  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c
