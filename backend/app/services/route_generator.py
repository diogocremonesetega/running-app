"""Native round_trip loop route generator with infrastructure custom models."""

from __future__ import annotations

import logging
import math
import random
import re
from dataclasses import dataclass
from typing import Any

import httpx
from shapely.geometry import mapping

from app.services import graphhopper

logger = logging.getLogger(__name__)

MAX_CUSTOM_MODEL_AREAS = 45
MAX_UNLIT_AREAS = 22
MAX_WATER_AREAS = 10
MAX_RESTROOM_AREAS = 10

ELEVATION_PROFILES = {
    "flat": "foot_flat_recovery",
    "moderate": "foot_elevation",
    "hilly": "foot_hill_training",
}


@dataclass
class InfrastructureFlags:
    avoid_traffic_signals: bool = False
    prioritize_well_lit_streets: bool = False
    prioritize_soft_surfaces: bool = False
    include_water: bool = False
    include_restrooms: bool = False


def _java_safe_area_id(raw: str) -> str:
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


def _bbox_string(
    center_lat: float,
    center_lng: float,
    radius_km: float,
) -> str:
    radius_deg = radius_km / 111.0
    min_lat = center_lat - radius_deg
    max_lat = center_lat + radius_deg
    min_lng = center_lng - radius_deg
    max_lng = center_lng + radius_deg
    return f"{min_lat},{min_lng},{max_lat},{max_lng}"


def _zone_to_polygon(z: dict[str, float]) -> dict:
    return {
        "type": "Polygon",
        "coordinates": [[
            [z["min_lng"], z["min_lat"]],
            [z["max_lng"], z["min_lat"]],
            [z["max_lng"], z["max_lat"]],
            [z["min_lng"], z["max_lat"]],
            [z["min_lng"], z["min_lat"]],
        ]],
    }


def _select_profile(elevation_preference: str) -> str:
    return ELEVATION_PROFILES.get(elevation_preference, "foot_elevation")


def _soft_surface_priority_rules() -> list[dict[str, str]]:
    return [
        {"if": "surface == GRASS || surface == DIRT || surface == GRAVEL", "multiply_by": "1.8"},
        {"else_if": "surface == GROUND || surface == WOOD || surface == UNPAVED", "multiply_by": "1.6"},
        {"else_if": "surface == COMPACTED || surface == FINE_GRAVEL", "multiply_by": "1.4"},
        {"else_if": "surface == ASPHALT || surface == PAVED", "multiply_by": "0.85"},
    ]


def _signal_priority_rules(elevation_preference: str) -> list[dict[str, str]]:
    if elevation_preference == "hilly":
        return [
            {"if": "road_class == PRIMARY", "multiply_by": "0.5"},
            {"else_if": "road_class == SECONDARY", "multiply_by": "0.8"},
            {"else_if": "road_class == TERTIARY", "multiply_by": "0.9"},
            {"else_if": "road_class == FOOTWAY || road_class == PATH || road_class == PEDESTRIAN", "multiply_by": "1.5"},
            {"else_if": "road_class == LIVING_STREET", "multiply_by": "1.3"},
            {"else_if": "road_class == RESIDENTIAL", "multiply_by": "1.2"},
            {"else_if": "road_class == CYCLEWAY", "multiply_by": "1.3"},
        ]
    return [
        {"if": "road_class == PRIMARY", "multiply_by": "0.3"},
        {"else_if": "road_class == SECONDARY", "multiply_by": "0.4"},
        {"else_if": "road_class == TERTIARY", "multiply_by": "0.6"},
        {"if": "road_class == FOOTWAY || road_class == PATH || road_class == PEDESTRIAN", "multiply_by": "2.0"},
        {"else_if": "road_class == LIVING_STREET", "multiply_by": "1.8"},
        {"else_if": "road_class == RESIDENTIAL", "multiply_by": "1.5"},
        {"else_if": "road_class == CYCLEWAY", "multiply_by": "1.6"},
    ]


def _elevation_priority_rules(elevation_preference: str) -> list[dict[str, str]]:
    if elevation_preference == "flat":
        return [
            {"if": "average_slope > 10 || average_slope < -10", "multiply_by": "0.01"},
            {"else_if": "average_slope > 6 || average_slope < -6", "multiply_by": "0.1"},
            {"else_if": "average_slope > 2 || average_slope < -2", "multiply_by": "0.3"},
            {"else_if": "average_slope > 1 || average_slope < -1", "multiply_by": "0.6"},
        ]
    if elevation_preference == "hilly":
        return [
            {"if": "average_slope > 12", "multiply_by": "5.0"},
            {"else_if": "average_slope > 8", "multiply_by": "3.5"},
            {"else_if": "average_slope > 4", "multiply_by": "2.0"},
            {"else_if": "average_slope > 2", "multiply_by": "1.3"},
            {"if": "average_slope < -12", "multiply_by": "5.0"},
            {"else_if": "average_slope < -8", "multiply_by": "3.5"},
            {"else_if": "average_slope < -4", "multiply_by": "2.0"},
            {"else_if": "average_slope < -2", "multiply_by": "1.3"},
        ]
    return []


def _distance_influence(elevation_preference: str) -> int:
    if elevation_preference in ("flat", "hilly"):
        return 15
    return 70


async def build_infrastructure_custom_model(
    start_lat: float,
    start_lng: float,
    distance_km: float,
    elevation_preference: str,
    flags: InfrastructureFlags,
) -> tuple[dict[str, Any] | None, str]:
    """Build GraphHopper custom_model and base profile for infrastructure toggles."""
    from app.services import osm_infrastructure

    profile = _select_profile(elevation_preference)
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

    bbox_radius_km = max(distance_km * 0.5, 2.0)
    bbox = _bbox_string(start_lat, start_lng, bbox_radius_km)

    if flags.prioritize_well_lit_streets:
        try:
            unlit = await osm_infrastructure.fetch_unlit_street_boxes(bbox)
            unlit.sort(
                key=lambda z: _haversine_km(
                    start_lat, start_lng,
                    (z["min_lat"] + z["max_lat"]) / 2,
                    (z["min_lng"] + z["max_lng"]) / 2,
                )
            )
            for i, z in enumerate(unlit[:MAX_UNLIT_AREAS]):
                _add_area(f"unlit_{i}", _zone_to_polygon(z), "0.2")
        except (httpx.HTTPStatusError, httpx.TimeoutException) as exc:
            logger.warning("Unlit street data unavailable: %s", exc)

    if flags.include_water:
        try:
            water = await osm_infrastructure.fetch_water_points(bbox)
            water.sort(
                key=lambda z: _haversine_km(
                    start_lat, start_lng,
                    (z["min_lat"] + z["max_lat"]) / 2,
                    (z["min_lng"] + z["max_lng"]) / 2,
                )
            )
            for i, z in enumerate(water[:MAX_WATER_AREAS]):
                _add_area(f"water_{i}", _zone_to_polygon(z), "1.5")
        except (httpx.HTTPStatusError, httpx.TimeoutException) as exc:
            logger.warning("Water POI data unavailable: %s", exc)

    if flags.include_restrooms:
        try:
            restrooms = await osm_infrastructure.fetch_restroom_points(bbox)
            restrooms.sort(
                key=lambda z: _haversine_km(
                    start_lat, start_lng,
                    (z["min_lat"] + z["max_lat"]) / 2,
                    (z["min_lng"] + z["max_lng"]) / 2,
                )
            )
            for i, z in enumerate(restrooms[:MAX_RESTROOM_AREAS]):
                _add_area(f"restroom_{i}", _zone_to_polygon(z), "1.5")
        except (httpx.HTTPStatusError, httpx.TimeoutException) as exc:
            logger.warning("Restroom POI data unavailable: %s", exc)

    max_radius_km = distance_km * 0.7
    radius_deg_lat = max_radius_km / 111.0
    radius_deg_lng = max_radius_km / (111.0 * math.cos(math.radians(start_lat)))
    local_bounds_poly = {
        "type": "Polygon",
        "coordinates": [[
            [start_lng - radius_deg_lng, start_lat - radius_deg_lat],
            [start_lng + radius_deg_lng, start_lat - radius_deg_lat],
            [start_lng + radius_deg_lng, start_lat + radius_deg_lat],
            [start_lng - radius_deg_lng, start_lat + radius_deg_lat],
            [start_lng - radius_deg_lng, start_lat - radius_deg_lat],
        ]],
    }
    _add_area("local_bounds", local_bounds_poly, "0")
    if area_pairs:
        last_feat, _ = area_pairs[-1]
        aid = last_feat["id"]
        area_pairs[-1] = (last_feat, {"if": f"!in_{aid}", "multiply_by": "0"})

    if len(area_pairs) > MAX_CUSTOM_MODEL_AREAS:
        area_pairs = area_pairs[:MAX_CUSTOM_MODEL_AREAS]

    priority_rules: list[dict[str, str]] = []
    if area_pairs:
        priority_rules.extend(p[1] for p in area_pairs)

    if flags.avoid_traffic_signals:
        priority_rules.extend(_signal_priority_rules(elevation_preference))

    if flags.prioritize_soft_surfaces:
        priority_rules.extend(_soft_surface_priority_rules())

    priority_rules.extend(_elevation_priority_rules(elevation_preference))

    areas_coll = None
    if area_pairs:
        areas_coll = {"type": "FeatureCollection", "features": [p[0] for p in area_pairs]}

    custom_model: dict[str, Any] | None = None
    if priority_rules:
        custom_model = {
            "priority": priority_rules,
            "distance_influence": _distance_influence(elevation_preference),
        }
        if areas_coll:
            custom_model["areas"] = areas_coll

    from app.config import settings
    if settings.graphhopper_api_key:
        custom_model = None
        profile = "foot"

    return custom_model, profile


def _route_properties(
    best_path: dict,
    profile: str,
    elevation_preference: str,
    flags: InfrastructureFlags,
) -> dict[str, Any]:
    return {
        "distance_m": round(best_path.get("distance", 0), 1),
        "distance_km": round(best_path.get("distance", 0) / 1000, 2),
        "time_ms": best_path.get("time", 0),
        "time_min": round(best_path.get("time", 0) / 60000, 1),
        "ascend_m": round(best_path.get("ascend", 0), 1),
        "descend_m": round(best_path.get("descend", 0), 1),
        "profile_used": profile,
        "elevation_preference": elevation_preference,
        "avoid_traffic_signals": flags.avoid_traffic_signals,
        "prioritize_well_lit_streets": flags.prioritize_well_lit_streets,
        "prioritize_soft_surfaces": flags.prioritize_soft_surfaces,
        "include_water": flags.include_water,
        "include_restrooms": flags.include_restrooms,
    }


def _compute_elevation_stats(profile: list[dict]) -> dict:
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


async def generate_point_to_point_route(
    start_lat: float,
    start_lng: float,
    end_lat: float,
    end_lng: float,
    elevation_preference: str = "moderate",
    flags: InfrastructureFlags | None = None,
) -> dict[str, Any]:
    """Point-to-point route with the same infrastructure custom model as loops."""
    flags = flags or InfrastructureFlags()
    span_km = _haversine_km(start_lat, start_lng, end_lat, end_lng)
    custom_model, profile = await build_infrastructure_custom_model(
        start_lat, start_lng, max(span_km, 2.0), elevation_preference, flags
    )
    waypoints = [(start_lat, start_lng), (end_lat, end_lng)]

    if custom_model:
        gh_response = await graphhopper.post_route_with_custom_model(
            waypoints=waypoints,
            profile=profile,
            custom_model=custom_model,
            elevation=True,
            details=["average_slope"],
        )
    else:
        gh_response = await graphhopper.get_route(
            waypoints=waypoints,
            profile=profile,
            elevation=True,
            details=["average_slope"],
        )

    if not gh_response.get("paths"):
        raise graphhopper.GraphHopperError(404, "No route found")

    best_path = gh_response["paths"][0]
    elevation_profile = graphhopper.extract_elevation_profile(best_path)
    slope_segments = graphhopper.extract_slope_segments(best_path)

    return {
        "route": {
            "type": "Feature",
            "geometry": best_path.get("points", {}),
            "properties": _route_properties(best_path, profile, elevation_preference, flags),
        },
        "elevation_profile": elevation_profile,
        "elevation_stats": _compute_elevation_stats(elevation_profile),
        "slope_segments": slope_segments,
    }


async def generate_loop_route(
    start_lat: float,
    start_lng: float,
    distance_km: float,
    elevation_preference: str = "moderate",
    avoid_traffic_signals: bool = False,
    prioritize_well_lit_streets: bool = False,
    prioritize_soft_surfaces: bool = False,
    include_water: bool = False,
    include_restrooms: bool = False,
) -> dict[str, Any]:
    """Generate a loop running route via GraphHopper round_trip."""
    flags = InfrastructureFlags(
        avoid_traffic_signals=avoid_traffic_signals,
        prioritize_well_lit_streets=prioritize_well_lit_streets,
        prioritize_soft_surfaces=prioritize_soft_surfaces,
        include_water=include_water,
        include_restrooms=include_restrooms,
    )

    all_waypoints: list[tuple[float, float]] = [(start_lat, start_lng)]
    peak_waypoint_index: int | None = None

    if elevation_preference == "hilly":
        from app.services import spatial_queries as _sq_peak
        search_radius_m = (distance_km * 1000.0) * 0.60
        peak = await _sq_peak.find_highest_peak_near(start_lat, start_lng, radius_m=search_radius_m)
        if peak:
            logger.info(
                "Hilly anchor: %s (%.0fm) @ %.5f, %.5f",
                peak["name"], peak["ele"], peak["lat"], peak["lng"],
            )
            bearing_to_peak = math.atan2(peak["lng"] - start_lng, peak["lat"] - start_lat)
            offset_deg = (distance_km * 0.30) / 111.0
            jitter = random.uniform(-0.4, 0.4)
            return_bearing = bearing_to_peak + math.pi + jitter
            return_lat = start_lat + offset_deg * math.cos(return_bearing)
            return_lng = start_lng + offset_deg * math.sin(return_bearing)
            all_waypoints = [
                (start_lat, start_lng),
                (peak["lat"], peak["lng"]),
                (return_lat, return_lng),
                (start_lat, start_lng),
            ]
            peak_waypoint_index = 1
        else:
            logger.warning("No OSM peak found — falling back to round_trip")

    custom_model, profile = await build_infrastructure_custom_model(
        start_lat, start_lng, distance_km, elevation_preference, flags
    )
    safe_seed = random.randint(0, 100000)
    gh_response: dict[str, Any] | None = None

    if elevation_preference == "hilly" and peak_waypoint_index is not None:
        try:
            if custom_model:
                gh_response = await graphhopper.post_route_with_custom_model(
                    waypoints=all_waypoints,
                    profile=profile,
                    custom_model=custom_model,
                    elevation=True,
                    details=["average_slope"],
                    algorithm=None,
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
            logger.warning("Peak-anchored route failed (%s) — round_trip fallback", exc.status_code)
            all_waypoints = [(start_lat, start_lng)]
            peak_waypoint_index = None
            gh_response = None

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
            return {
                "error": "Route generation failed",
                "warning": (
                    f"The routing engine could not find a valid path for {distance_km} km "
                    f"({elevation_preference}). Try a shorter distance or moderate profile."
                ),
                "graphhopper_status": exc.status_code,
                "waypoints_generated": [{"lat": start_lat, "lng": start_lng}],
            }

    if not gh_response or not gh_response.get("paths"):
        return {
            "error": "No route found",
            "warning": (
                f"No viable path for {distance_km} km {elevation_preference} route. "
                "Try a shorter distance or different profile."
            ),
            "waypoints_generated": [{"lat": start_lat, "lng": start_lng}],
        }

    best_path = gh_response["paths"][0]
    elevation_profile = graphhopper.extract_elevation_profile(best_path)
    slope_segments = graphhopper.extract_slope_segments(best_path)

    return {
        "route": {
            "type": "Feature",
            "geometry": best_path.get("points", {}),
            "properties": _route_properties(best_path, profile, elevation_preference, flags),
        },
        "elevation_profile": elevation_profile,
        "slope_segments": slope_segments,
        "elevation_stats": _compute_elevation_stats(elevation_profile),
        "waypoints_generated": [{"lat": start_lat, "lng": start_lng}],
        "instructions": best_path.get("instructions", []),
    }
