"""Circle-based loop route generator.

Generates running loops by placing waypoints on a circle around a
starting point, then routing through them via GraphHopper.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

from shapely.geometry import shape, mapping

from app.services import graphhopper

# GraphHopper compiles one Java statement per area; hundreds of areas (e.g. unlit OSM ways)
# produces a Janino subclass that fails to compile. Keep total dynamic areas small.
MAX_CUSTOM_MODEL_AREAS = 45
MAX_UNLIT_AREAS = 22


def _java_safe_area_id(raw: str) -> str:
    """Area ids become Java identifiers like `feature_<id>`; only [a-zA-Z0-9_] allowed."""
    s = re.sub(r"[^a-zA-Z0-9_]", "_", raw)
    if not s or s[0].isdigit():
        s = "a_" + s
    return s


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlng / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(h)))


def _to_polygon_geometry(geojson_geom: dict) -> dict | None:
    """Convert GeoJSON geometry to a single Polygon for GraphHopper.

    GraphHopper only supports Polygon. MultiPolygon uses the largest part.
    """
    geom = shape(geojson_geom)
    if geom.geom_type == "Polygon":
        return mapping(geom)
    if geom.geom_type == "MultiPolygon":
        # Use largest polygon by area
        largest = max(geom.geoms, key=lambda g: g.area)
        return mapping(largest)
    return None


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
    avoid_unlit_streets: bool = False,
    prefer_scenic: bool = False,
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
    # GraphHopper v10: areas = FeatureCollection; each feature needs "id".
    # Too many areas → Janino-generated init() blows up and fails to compile.
    area_pairs: list[tuple[dict[str, Any], dict[str, str]]] = []
    used_ids: set[str] = set()

    def _add_area(suggested_id: str, geometry: dict, multiply_by: str) -> None:
        aid = _java_safe_area_id(suggested_id)
        base = aid
        n = 0
        while aid in used_ids:
            n += 1
            aid = f"{base}_{n}"
        used_ids.add(aid)
        feat = {"type": "Feature", "id": aid, "geometry": geometry}
        area_pairs.append((feat, {"if": f"in_{aid}", "multiply_by": multiply_by}))

    # --- Closure zones (PostGIS) — block routing through closures ---
    from app.services import spatial_queries as _sq
    closure_zones = await _sq.get_active_closures(start_lat, start_lng, radius_m=5000)
    for i, z in enumerate(closure_zones):
        geojson = json.loads(z["geojson"])
        poly = _to_polygon_geometry(geojson)
        if poly:
            _add_area(f"closure_{i}", poly, "0")

    # --- Safety zones (PostGIS) ---
    if prioritize_safety:
        from app.services import spatial_queries
        safety_zones = await spatial_queries.get_active_safety_zones(start_lat, start_lng, radius_m=5000)
        for i, z in enumerate(safety_zones):
            geojson = json.loads(z["geojson"])
            poly = _to_polygon_geometry(geojson)
            if poly:
                penalty = str(round(max(0.1, z["safety_score"] / 100), 2))
                _add_area(f"safety_{i}", poly, penalty)

    # --- Scenic + unlit (only when prefer_scenic) ---
    if prefer_scenic:
        from app.services import spatial_queries as _sq2
        from app.services import lighting_data

        scenic_segs = await _sq2.get_scenic_segments_near(start_lat, start_lng, radius_m=4000)
        for i, s in enumerate(scenic_segs):
            geojson = json.loads(s["geojson"])
            geom = shape(geojson)
            buffered = geom.buffer(0.0001)
            poly = _to_polygon_geometry(mapping(buffered))
            if poly:
                boost = str(round(1.0 + (s["gvi_score"] * 2), 1))
                _add_area(f"scenic_{i}", poly, boost)

        lats = [wp[0] for wp in all_waypoints]
        lngs = [wp[1] for wp in all_waypoints]
        min_lat, max_lat = min(lats) - 0.005, max(lats) + 0.005
        min_lng, max_lng = min(lngs) - 0.005, max(lngs) + 0.005
        bbox = f"{min_lat},{min_lng},{max_lat},{max_lng}"
        unlit_zones = await lighting_data.fetch_unlit_streets(bbox)

        def _unlit_sort_key(z: dict[str, float]) -> float:
            clat = (z["min_lat"] + z["max_lat"]) / 2
            clng = (z["min_lng"] + z["max_lng"]) / 2
            return _haversine_km(start_lat, start_lng, clat, clng)

        unlit_zones = sorted(unlit_zones, key=_unlit_sort_key)[:MAX_UNLIT_AREAS]

        for i, z in enumerate(unlit_zones):
            poly = {
                "type": "Polygon",
                "coordinates": [[
                    [z["min_lng"], z["min_lat"]],
                    [z["max_lng"], z["min_lat"]],
                    [z["max_lng"], z["max_lat"]],
                    [z["min_lng"], z["max_lat"]],
                    [z["min_lng"], z["min_lat"]],
                ]],
            }
            _add_area(f"unlit_{i}", poly, "0.2")

    # Cap total areas (closures + safety + scenic + unlit)
    if len(area_pairs) > MAX_CUSTOM_MODEL_AREAS:
        area_pairs = area_pairs[:MAX_CUSTOM_MODEL_AREAS]

    custom_model: dict[str, Any] | None = None
    if area_pairs:
        features = [p[0] for p in area_pairs]
        priority_rules = [p[1] for p in area_pairs]
        custom_model = {
            "areas": {"type": "FeatureCollection", "features": features},
            "priority": priority_rules,
        }

    from app.config import settings
    if settings.graphhopper_api_key:
        if not custom_model:
            custom_model = {"priority": []}
        if "priority" not in custom_model:
            custom_model["priority"] = []

        if profile == "foot_flat_recovery":
            custom_model["priority"].extend([
                {"if": "slope > 6", "multiply_by": "0.1"},
                {"if": "slope < -6", "multiply_by": "0.1"}
            ])
        elif profile == "foot_hill_training":
            custom_model["priority"].append({"if": "slope > 4", "multiply_by": "1.5"})
        elif profile == "foot_no_signals":
            custom_model["priority"].append({"if": "toll == toll", "multiply_by": "0.5"})

        profile = "foot"

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
                "avoid_unlit_streets": avoid_unlit_streets,
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
