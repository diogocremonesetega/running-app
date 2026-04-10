"""Native round_trip loop route generator.

Generates running loops by invoking GraphHopper's built-in round_trip
algorithm from a single start point. Custom model area overlays (safety
zones, closures, scenic segments, unlit streets) are composed per-request
and submitted alongside the algorithm directive.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

import httpx
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



# --- Profile selection ---

ELEVATION_PROFILES = {
    "flat": "foot_flat_recovery",
    "moderate": "foot_elevation",
    "hilly": "foot_hill_training",
}

SIGNAL_AVOIDANCE_PROFILE = "foot_no_signals"


def _select_profile(elevation_preference: str) -> str:
    """Select the GraphHopper profile based purely on the elevation preference.
    Signal avoidance is injected dynamically at runtime via custom_models.
    """
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
    start_bearing: float = 0.0,
) -> dict[str, Any]:
    """Generate a loop running route with elevation and signal awareness using GraphHopper's round_trip API.

    Flow:
    1. Define the start point.
    2. Select the appropriate GraphHopper profile.
    3. Call GraphHopper with algorithm="round_trip" and the distance parameter.
    4. Extract elevation profile and slope data.

    Args:
        start_lat: Starting latitude.
        start_lng: Starting longitude.
        distance_km: Target total distance in km.
        elevation_preference: "flat", "moderate", or "hilly".
        avoid_traffic_signals: Penalize roads with traffic signals.
        start_bearing: Seed value (0-359) that controls which loop variant
            GraphHopper produces. Same start + same bearing = same route.
            Different bearing = different organic loop from the same start.

    Returns:
        Dict with route data, elevation profile, and metadata.
    """
    import random

    # 1. Define start point. For hilly mode, we'll inject a peak anchor below.
    all_waypoints: list[tuple[float, float]] = [(start_lat, start_lng)]
    peak_waypoint_index: int | None = None  # tracks which waypoint is the summit

    # 2. Select base elevation profile
    profile = _select_profile(elevation_preference)

    # --- Step 1 & 2: Spatial Elevation Query + Waypoint Injection (Hilly mode only) ---
    if elevation_preference == "hilly":
        from app.services import spatial_queries as _sq_peak
        # Search within ~60% of the run radius so we don't anchor too far away
        search_radius_m = (distance_km * 1000.0) * 0.60
        peak = await _sq_peak.find_highest_peak_near(start_lat, start_lng, radius_m=search_radius_m)

        if peak:
            import logging as _log
            _log.getLogger(__name__).info(
                "Hilly anchor: %s (%.0fm elev) @ %.5f, %.5f",
                peak["name"], peak["ele"], peak["lat"], peak["lng"]
            )
            # Inject: start → peak → semi-random return point → back to start
            # Semi-random return point: offset from start in the opposite direction of the peak
            bearing_to_peak = math.atan2(
                peak["lng"] - start_lng,
                peak["lat"] - start_lat
            )
            # Place return waypoint roughly 30% of distance_km on the opposite side
            offset_km = distance_km * 0.30
            offset_deg = offset_km / 111.0
            jitter = random.uniform(-0.4, 0.4)  # radians, ~±23°
            return_bearing = bearing_to_peak + math.pi + jitter
            return_lat = start_lat + offset_deg * math.cos(return_bearing)
            return_lng = start_lng + offset_deg * math.sin(return_bearing)

            # Build: [start, peak, return_point, start]
            all_waypoints = [
                (start_lat, start_lng),
                (peak["lat"], peak["lng"]),   # index 1 = summit (pass_through)
                (return_lat, return_lng),
                (start_lat, start_lng),        # close the loop
            ]
            peak_waypoint_index = 1  # Step 3: flag summit for U-turn allowance
        else:
            import logging as _log
            _log.getLogger(__name__).warning("No OSM peak found within %.0fm — falling back to round_trip", search_radius_m)

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
        try:
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

            # Bounding box calculation for unlit areas based on expected route radius
            # Roughly estimate 1 degree ~ 111km
            radius_deg = (distance_km / 2.0) / 111.0
            min_lat, max_lat = start_lat - radius_deg, start_lat + radius_deg
            min_lng, max_lng = start_lng - radius_deg, start_lng + radius_deg
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

        except httpx.HTTPStatusError as exc:
            import logging as _log
            _log.getLogger(__name__).warning(
                "Scenic/unlit data unavailable (HTTP %s) — route will be generated without scenic multipliers.",
                exc.response.status_code,
            )
        except httpx.TimeoutException:
            import logging as _log
            _log.getLogger(__name__).warning(
                "Overpass API timed out fetching scenic/unlit data — route will be generated without scenic multipliers."
            )
        except Exception as exc:
            import logging as _log
            _log.getLogger(__name__).error(
                "Scenic data fetch failed (%s: %s) — route will be generated without scenic multipliers.",
                type(exc).__name__, exc,
            )

    # --- Local area bounding box (prevents routing across flat bridges leading deep out of the city) ---
    # Clamp the bounding radius: a round-trip loop covers at most ~half the distance outward.
    # Use 0.7x as geofence radius, but ensure the requested distance is achievable within it.
    max_radius_km = distance_km * 0.7
    radius_deg_lat = max_radius_km / 111.0
    radius_deg_lng = max_radius_km / (111.0 * math.cos(math.radians(start_lat)))
    bbox_min_lat, bbox_max_lat = start_lat - radius_deg_lat, start_lat + radius_deg_lat
    bbox_min_lng, bbox_max_lng = start_lng - radius_deg_lng, start_lng + radius_deg_lng
    local_bounds_poly = {
        "type": "Polygon",
        "coordinates": [[
            [bbox_min_lng, bbox_min_lat],
            [bbox_max_lng, bbox_min_lat],
            [bbox_max_lng, bbox_max_lat],
            [bbox_min_lng, bbox_max_lat],
            [bbox_min_lng, bbox_min_lat]
        ]]
    }
    # Register via _add_area so the feature id and priority rule share the same
    # standardised naming pattern GraphHopper requires (in_<id> / !in_<id>).
    # multiply_by "0" creates an absolute impassable boundary — no edge outside
    # the polygon can ever be traversed.
    _add_area("local_bounds", local_bounds_poly, "0")
    # Override the rule produced by _add_area to use the NEGATION (!in_local_bounds)
    # so it blocks roads OUTSIDE the fence, not inside it.
    if area_pairs and area_pairs[-1][1].get("if", "").startswith("in_"):
        last_feat, _ = area_pairs[-1]
        aid = last_feat["id"]
        area_pairs[-1] = (last_feat, {"if": f"!in_{aid}", "multiply_by": "0"})

    # Cap total areas (closures + safety + scenic + unlit)
    if len(area_pairs) > MAX_CUSTOM_MODEL_AREAS:
        area_pairs = area_pairs[:MAX_CUSTOM_MODEL_AREAS]

    priority_rules: list[dict[str, str]] = []
    
    if area_pairs:
        features = [p[0] for p in area_pairs]
        areas_coll = {"type": "FeatureCollection", "features": features}
        priority_rules.extend(p[1] for p in area_pairs)
    else:
        areas_coll = None

    if avoid_traffic_signals:
        if elevation_preference == "hilly":
            # Relax signal penalties for Hilly so steep secondary avenues aren't falsely rejected in favor of flat residential grids.
            priority_rules.extend([
                {"if": "road_class == PRIMARY", "multiply_by": "0.5"},
                {"else_if": "road_class == SECONDARY", "multiply_by": "0.8"},
                {"else_if": "road_class == TERTIARY", "multiply_by": "0.9"},
                {"else_if": "road_class == FOOTWAY || road_class == PATH || road_class == PEDESTRIAN", "multiply_by": "1.5"},
                {"else_if": "road_class == LIVING_STREET", "multiply_by": "1.3"},
                {"else_if": "road_class == RESIDENTIAL", "multiply_by": "1.2"},
                {"else_if": "road_class == CYCLEWAY", "multiply_by": "1.3"}
            ])
        else:
            # Standard strict signal penalties
            priority_rules.extend([
                {"if": "road_class == PRIMARY", "multiply_by": "0.3"},
                {"else_if": "road_class == SECONDARY", "multiply_by": "0.4"},
                {"else_if": "road_class == TERTIARY", "multiply_by": "0.6"},
                {"if": "road_class == FOOTWAY || road_class == PATH || road_class == PEDESTRIAN", "multiply_by": "2.0"},
                {"else_if": "road_class == LIVING_STREET", "multiply_by": "1.8"},
                {"else_if": "road_class == RESIDENTIAL", "multiply_by": "1.5"},
                {"else_if": "road_class == CYCLEWAY", "multiply_by": "1.6"}
            ])

    # Enforce strict terrain bounds directly in the routing calculation using interval steps
    if elevation_preference == "flat":
        priority_rules.extend([
            {"if": "average_slope > 10 || average_slope < -10", "multiply_by": "0.01"},
            {"else_if": "average_slope > 6 || average_slope < -6", "multiply_by": "0.1"},
            {"else_if": "average_slope > 2 || average_slope < -2", "multiply_by": "0.3"},
            {"else_if": "average_slope > 1 || average_slope < -1", "multiply_by": "0.6"}
        ])
    elif elevation_preference == "hilly":
        priority_rules.extend([
            {"if": "average_slope > 12", "multiply_by": "5.0"},
            {"else_if": "average_slope > 8", "multiply_by": "3.5"},
            {"else_if": "average_slope > 4", "multiply_by": "2.0"},
            {"else_if": "average_slope > 2", "multiply_by": "1.3"},
            {"if": "average_slope < -12", "multiply_by": "5.0"},
            {"else_if": "average_slope < -8", "multiply_by": "3.5"},
            {"else_if": "average_slope < -4", "multiply_by": "2.0"},
            {"else_if": "average_slope < -2", "multiply_by": "1.3"}
        ])

    # Force routing behavior by dynamically shifting the distance influence metrics
    # Extreme low influence forces the algorithm to explore exclusively for mathematical elevation bounds
    if elevation_preference == "flat":
        dist_influence = 15
    elif elevation_preference == "hilly":
        dist_influence = 15
    else:
        dist_influence = 70

    custom_model: dict[str, Any] | None = None
    if priority_rules:
        custom_model = {
            "priority": priority_rules,
            "distance_influence": dist_influence
        }
        if areas_coll:
            custom_model["areas"] = areas_coll

    from app.config import settings
    if settings.graphhopper_api_key:
        # Free public API completely bans custom_model and flexible routing.
        # We must aggressively strip the custom model and degrade to a standard route.
        custom_model = None
        profile = "foot"

    safe_seed = random.randint(0, 100000)

    gh_response: dict[str, Any] | None = None

    if elevation_preference == "hilly" and peak_waypoint_index is not None:
        # ── Peak-anchored hilly route: A → Summit → Return → A ──
        # No round_trip algorithm; we use a standard multi-waypoint route.
        # pass_through on the summit index allows U-turns at dead-end lookouts.
        try:
            if custom_model:
                gh_response = await graphhopper.post_route_with_custom_model(
                    waypoints=all_waypoints,
                    profile=profile,
                    custom_model=custom_model,
                    elevation=True,
                    details=["average_slope"],
                    algorithm=None,  # Standard A→B→C routing, not round_trip
                    pass_through_indices=[peak_waypoint_index],
                )
            else:
                gh_response = await graphhopper.get_route(
                    waypoints=all_waypoints,
                    profile=profile,
                    elevation=True,
                    details=["average_slope"],
                )
        except graphhopper.GraphHopperError as exc:
            import logging as _log
            _log.getLogger(__name__).warning(
                "Peak-anchored hilly route failed (GH %s) — falling back to round_trip.",
                exc.status_code,
            )
            # Reset to single-waypoint round_trip fallback
            all_waypoints = [(start_lat, start_lng)]
            peak_waypoint_index = None
            gh_response = None

    # Standard round_trip path (used for flat/moderate, and as fallback for failed hilly)
    if gh_response is None:
        try:
            if custom_model:
                gh_response = await graphhopper.post_route_with_custom_model(
                    waypoints=all_waypoints,
                    profile=profile,
                    custom_model=custom_model,
                    elevation=True,
                    details=["average_slope"],
                    algorithm="round_trip",
                    round_trip_distance_m=distance_km * 1000.0,
                    round_trip_seed=safe_seed,
                )
            else:
                gh_response = await graphhopper.get_route(
                    waypoints=all_waypoints,
                    profile=profile,
                    elevation=True,
                    details=["average_slope"],
                    algorithm="round_trip",
                    round_trip_distance_m=distance_km * 1000.0,
                    round_trip_seed=safe_seed,
                )
        except graphhopper.GraphHopperError as exc:
            import logging as _log
            _log.getLogger(__name__).error(
                "GraphHopper routing failed entirely (GH %s): %s",
                exc.status_code, exc.detail[:200],
            )
            return {
                "error": "Route generation failed",
                "warning": (
                    f"The routing engine could not find a valid path. "
                    f"This may happen if the requested distance ({distance_km} km) exceeds "
                    f"the routable area, or if elevation constraints are too strict. "
                    f"Try reducing the distance or switching to a moderate profile."
                ),
                "graphhopper_status": exc.status_code,
                "waypoints_generated": [{"lat": start_lat, "lng": start_lng}],
            }

    # 5. Parse the best path
    if not gh_response or not gh_response.get("paths"):
        return {
            "error": "No route found",
            "warning": (
                f"GraphHopper returned no viable path for a {distance_km} km "
                f"{elevation_preference} route from ({start_lat:.4f}, {start_lng:.4f}). "
                f"The strict bounding constraints or elevation penalties may have "
                f"eliminated all candidates. Try a shorter distance or a different profile."
            ),
            "waypoints_generated": [{"lat": start_lat, "lng": start_lng}],
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
        "waypoints_generated": [{"lat": start_lat, "lng": start_lng}],
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
