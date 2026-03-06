"""Circle-based loop route generator.

Generates running loops by placing waypoints on a circle around a
starting point, then routing through them via GraphHopper.
"""

from __future__ import annotations

import math
from typing import Any

from app.services import graphhopper


# --- Geometry helpers ---

def _destination_point(lat: float, lng: float, bearing_deg: float, distance_km: float) -> tuple[float, float]:
    """Compute destination point given start, bearing, and distance.

    Uses the Vincenty direct formula (spherical approximation).

    Args:
        lat: Start latitude in degrees.
        lng: Start longitude in degrees.
        bearing_deg: Bearing in degrees (0=North, 90=East).
        distance_km: Distance in kilometers.

    Returns:
        (lat, lng) of the destination point.
    """
    R = 6371.0  # Earth radius in km
    d = distance_km / R  # angular distance in radians

    lat1 = math.radians(lat)
    lng1 = math.radians(lng)
    brng = math.radians(bearing_deg)

    lat2 = math.asin(
        math.sin(lat1) * math.cos(d) + math.cos(lat1) * math.sin(d) * math.cos(brng)
    )
    lng2 = lng1 + math.atan2(
        math.sin(brng) * math.sin(d) * math.cos(lat1),
        math.cos(d) - math.sin(lat1) * math.sin(lat2),
    )

    return (math.degrees(lat2), math.degrees(lng2))


def generate_circle_waypoints(
    center_lat: float,
    center_lng: float,
    distance_km: float,
    num_waypoints: int = 5,
    start_bearing: float = 0.0,
) -> list[tuple[float, float]]:
    """Generate waypoints on a circle for a loop route.

    Places N waypoints evenly distributed on a circle around the
    center point. The circle radius is derived from the target
    total route distance: r ≈ distance / (2π).

    Args:
        center_lat: Center latitude (start/end point).
        center_lng: Center longitude (start/end point).
        distance_km: Target total route distance in km.
        num_waypoints: Number of intermediate waypoints.
        start_bearing: Initial bearing offset in degrees.

    Returns:
        List of (lat, lng) waypoints (does NOT include start/end).
    """
    # Radius of the circle — approximate so total loop ≈ target distance
    radius_km = distance_km / (2 * math.pi)

    # Distribute waypoints evenly around the circle
    bearing_step = 360.0 / num_waypoints
    waypoints = []

    for i in range(num_waypoints):
        bearing = (start_bearing + i * bearing_step) % 360
        wp = _destination_point(center_lat, center_lng, bearing, radius_km)
        waypoints.append(wp)

    return waypoints


# --- Profile selection ---

ELEVATION_PROFILES = {
    "flat": "foot_flat_recovery",
    "moderate": "foot_elevation",
    "hilly": "foot_hill_training",
}

SIGNAL_AVOIDANCE_PROFILE = "foot_no_signals"


def _select_profile(elevation_preference: str, avoid_traffic_signals: bool) -> str:
    """Select the best GraphHopper profile based on user preferences.

    If traffic signal avoidance is requested, we use the dedicated
    foot_no_signals profile. Elevation preferences are only applied
    when signal avoidance is off (the no-signals profile already
    includes moderate elevation handling).
    """
    if avoid_traffic_signals:
        return SIGNAL_AVOIDANCE_PROFILE
    return ELEVATION_PROFILES.get(elevation_preference, "foot_elevation")


# --- Main route generation ---

async def generate_loop_route(
    start_lat: float,
    start_lng: float,
    distance_km: float,
    elevation_preference: str = "moderate",
    avoid_traffic_signals: bool = False,
    prioritize_safety: bool = False,
    num_waypoints: int = 5,
    start_bearing: float = 0.0,
) -> dict[str, Any]:
    """Generate a loop running route with elevation and signal awareness.

    Flow:
    1. Generate circle-based waypoints around the start.
    2. Build the full waypoint list: start → wp1 → wp2 → ... → wpN → start.
    3. Select the appropriate GraphHopper profile.
    4. Call GraphHopper and parse the response.
    5. Extract elevation profile and slope data.

    Args:
        start_lat: Starting latitude.
        start_lng: Starting longitude.
        distance_km: Target total distance in km.
        elevation_preference: "flat", "moderate", or "hilly".
        avoid_traffic_signals: Penalize roads with traffic signals.
        num_waypoints: Number of intermediate circle waypoints.
        start_bearing: Compass bearing for the first waypoint.

    Returns:
        Dict with route data, elevation profile, and metadata.
    """
    # 1. Generate waypoints
    circle_wps = generate_circle_waypoints(
        center_lat=start_lat,
        center_lng=start_lng,
        distance_km=distance_km,
        num_waypoints=num_waypoints,
        start_bearing=start_bearing,
    )

    # 2. Build full waypoint sequence (loop: start → waypoints → start)
    all_waypoints = [(start_lat, start_lng)] + circle_wps + [(start_lat, start_lng)]

    # 3. Select profile
    profile = _select_profile(elevation_preference, avoid_traffic_signals)

    # 4. Call GraphHopper
    custom_model = None
    if prioritize_safety:
        from app.services import police_data
        incidents = await police_data.fetch_safety_data()
        zones = police_data.get_danger_zones(incidents)
        if zones:
            areas = {}
            priority_rules = []
            for i, z in enumerate(zones):
                area_id = f"danger_zone_{i}"
                areas[area_id] = {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[
                            [z["min_lng"], z["min_lat"]],
                            [z["max_lng"], z["min_lat"]],
                            [z["max_lng"], z["max_lat"]],
                            [z["min_lng"], z["max_lat"]],
                            [z["min_lng"], z["min_lat"]],
                        ]]
                    }
                }
                priority_rules.append({
                    "if": f"in_{area_id}",
                    "multiply_by": "0.1"
                })
            custom_model = {
                "areas": areas,
                "priority": priority_rules
            }

    if custom_model:
        gh_response = await graphhopper.post_route_with_custom_model(
            waypoints=all_waypoints,
            profile=profile,
            custom_model=custom_model,
            elevation=True,
            details=["average_slope"],
        )
    else:
        gh_response = await graphhopper.get_route(
            waypoints=all_waypoints,
            profile=profile,
            elevation=True,
            details=["average_slope"],
        )

    # 5. Parse the best path
    if not gh_response.get("paths"):
        return {
            "error": "No route found",
            "waypoints_generated": [{"lat": w[0], "lng": w[1]} for w in circle_wps],
        }

    best_path = gh_response["paths"][0]

    # 6. Extract elevation profile
    elevation_profile = graphhopper.extract_elevation_profile(best_path)
    slope_segments = graphhopper.extract_slope_segments(best_path)

    # 7. Build response
    return {
        "route": {
            "type": "Feature",
            "geometry": best_path.get("points", {}),
            "properties": {
                "distance_m": round(best_path.get("distance", 0), 1),
                "distance_km": round(best_path.get("distance", 0) / 1000, 2),
                "time_ms": best_path.get("time", 0),
                "time_min": round(best_path.get("time", 0) / 60000, 1),
                "ascend_m": round(best_path.get("ascend", 0), 1),
                "descend_m": round(best_path.get("descend", 0), 1),
                "profile_used": profile,
                "elevation_preference": elevation_preference,
                "avoid_traffic_signals": avoid_traffic_signals,
                "prioritize_safety": prioritize_safety,
            },
        },
        "elevation_profile": elevation_profile,
        "slope_segments": slope_segments,
        "elevation_stats": _compute_elevation_stats(elevation_profile),
        "waypoints_generated": [{"lat": w[0], "lng": w[1]} for w in circle_wps],
        "instructions": best_path.get("instructions", []),
    }


def _compute_elevation_stats(profile: list[dict]) -> dict:
    """Compute summary statistics from the elevation profile."""
    if not profile:
        return {}

    elevations = [p["elevation_m"] for p in profile]
    return {
        "min_elevation_m": min(elevations),
        "max_elevation_m": max(elevations),
        "elevation_range_m": round(max(elevations) - min(elevations), 1),
        "start_elevation_m": elevations[0],
        "end_elevation_m": elevations[-1],
        "num_points": len(elevations),
        "total_distance_m": profile[-1]["distance_m"] if profile else 0,
    }
