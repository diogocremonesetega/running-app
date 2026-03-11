"""API router for route generation endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Literal
import httpx

from app.services import route_generator, graphhopper, spatial_queries, weather_data

router = APIRouter(prefix="/api/v1", tags=["routes"])


# --- Request / Response models ---

class Coordinate(BaseModel):
    lat: float = Field(..., ge=-90, le=90, description="Latitude")
    lng: float = Field(..., ge=-180, le=180, description="Longitude")


class GenerateRouteRequest(BaseModel):
    start: Coordinate
    distance_km: float = Field(5.0, gt=0.5, le=50, description="Target distance in km")
    elevation_preference: Literal["flat", "moderate", "hilly"] = "moderate"
    avoid_traffic_signals: bool = False
    prioritize_safety: bool = False
    avoid_unlit_streets: bool = False
    num_waypoints: int = Field(5, ge=3, le=12, description="Circle waypoints")
    start_bearing: float = Field(0.0, ge=0, lt=360, description="Initial bearing offset")


class PointToPointRequest(BaseModel):
    """Simple point-to-point route (no loop)."""
    start: Coordinate
    end: Coordinate
    elevation_preference: Literal["flat", "moderate", "hilly"] = "moderate"
    avoid_traffic_signals: bool = False
    avoid_unlit_streets: bool = False


# --- Endpoints ---

@router.post("/generate-route")
async def generate_route(req: GenerateRouteRequest):
    """Generate a loop running route with circle-based waypoints.

    Returns the route GeoJSON, elevation profile, slope segments,
    and summary statistics.
    """
    try:
        result = await route_generator.generate_loop_route(
            start_lat=req.start.lat,
            start_lng=req.start.lng,
            distance_km=req.distance_km,
            elevation_preference=req.elevation_preference,
            avoid_traffic_signals=req.avoid_traffic_signals,
            prioritize_safety=req.prioritize_safety,
            avoid_unlit_streets=req.avoid_unlit_streets,
            num_waypoints=req.num_waypoints,
            start_bearing=req.start_bearing,
        )
        
        # Append environmental conditions to the response
        env_data = await weather_data.fetch_current_conditions(req.start.lat, req.start.lng)
        result["environmental_conditions"] = env_data
        
        return result
    except graphhopper.GraphHopperError as e:
        raise HTTPException(status_code=502, detail=f"GraphHopper error: {e.detail}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/point-to-point")
async def point_to_point_route(req: PointToPointRequest):
    """Generate a simple point-to-point route with elevation data.

    Useful for verifying elevation profiles and comparing profiles.
    """
    profile_map = {
        "flat": "foot_flat_recovery",
        "moderate": "foot_elevation",
        "hilly": "foot_hill_training",
    }
    profile = "foot_no_signals" if req.avoid_traffic_signals else profile_map.get(req.elevation_preference, "foot_elevation")

    try:
        gh_response = await graphhopper.get_route(
            waypoints=[(req.start.lat, req.start.lng), (req.end.lat, req.end.lng)],
            profile=profile,
            elevation=True,
            details=["average_slope"],
        )

        if not gh_response.get("paths"):
            raise HTTPException(status_code=404, detail="No route found")

        best_path = gh_response["paths"][0]
        elevation_profile = graphhopper.extract_elevation_profile(best_path)
        slope_segments = graphhopper.extract_slope_segments(best_path)

        # Compute elevation stats
        elevation_stats = {}
        if elevation_profile:
            elevations = [p["elevation_m"] for p in elevation_profile]
            elevation_stats = {
                "min_elevation_m": min(elevations),
                "max_elevation_m": max(elevations),
                "elevation_range_m": round(max(elevations) - min(elevations), 1),
            }

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
                },
            },
            "elevation_profile": elevation_profile,
            "elevation_stats": elevation_stats,
            "slope_segments": slope_segments,
        }
    except graphhopper.GraphHopperError as e:
        raise HTTPException(status_code=502, detail=f"GraphHopper error: {e.detail}")


@router.get("/geocode")
async def geocode(q: str, limit: int = 5):
    """Geocode an address/place name to coordinates using Nominatim.

    Biased toward the Berkeley/Bay Area for best results.
    """
    if not q or len(q.strip()) < 2:
        return {"results": []}

    params = {
        "q": q,
        "format": "jsonv2",
        "limit": min(limit, 8),
        "addressdetails": 1,
        "viewbox": "-122.35,37.95,-122.15,37.83",  # Berkeley/Oakland bounding box
        "bounded": 0,  # Prefer but don't restrict to viewbox
        "countrycodes": "us",
    }

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                "https://nominatim.openstreetmap.org/search",
                params=params,
                headers={"User-Agent": "RunningRouteGenerator/1.0"},
            )
            data = resp.json()

        results = []
        for item in data:
            results.append({
                "display_name": item.get("display_name", ""),
                "lat": float(item.get("lat", 0)),
                "lng": float(item.get("lon", 0)),
                "type": item.get("type", ""),
                "category": item.get("category", ""),
                "importance": item.get("importance", 0),
            })

        return {"results": results}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Geocoding error: {str(e)}")


@router.get("/reverse-geocode")
async def reverse_geocode(lat: float, lng: float):
    """Reverse geocode coordinates to an address using Nominatim."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                "https://nominatim.openstreetmap.org/reverse",
                params={
                    "lat": lat,
                    "lon": lng,
                    "format": "jsonv2",
                    "addressdetails": 1,
                },
                headers={"User-Agent": "RunningRouteGenerator/1.0"},
            )
            data = resp.json()

        return {
            "display_name": data.get("display_name", ""),
            "lat": float(data.get("lat", lat)),
            "lng": float(data.get("lon", lng)),
            "address": data.get("address", {}),
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Reverse geocoding error: {str(e)}")


@router.get("/profiles")
async def list_profiles():
    """List available routing profiles and their descriptions."""
    return {
        "profiles": [
            {
                "id": "foot_elevation",
                "name": "Balanced",
                "description": "Moderate elevation handling for everyday runs",
                "elevation_preference": "moderate",
            },
            {
                "id": "foot_flat_recovery",
                "name": "Flat Recovery",
                "description": "Aggressively avoids hills for easy recovery runs",
                "elevation_preference": "flat",
            },
            {
                "id": "foot_hill_training",
                "name": "Hill Training",
                "description": "Actively seeks elevation gain for challenging workouts",
                "elevation_preference": "hilly",
            },
            {
                "id": "foot_no_signals",
                "name": "No Traffic Signals",
                "description": "Avoids signal-heavy roads, prefers greenways and paths",
                "avoid_traffic_signals": True,
            },
        ]
    }


@router.get("/health")
async def health():
    """Health check for the backend and GraphHopper connection."""
    gh_status = await graphhopper.health_check()
    return {
        "backend": "ok",
        "graphhopper": gh_status,
    }



@router.get("/safety-overlay")
async def safety_overlay(lat: float, lng: float, radius_m: float = 5000):
    """Return current safety zones and road closures near a location as GeoJSON.

    Frontend uses this to render hazard overlays on the map. Data is sourced
    from PostGIS (populated by background workers every 30 minutes).
    """
    try:
        safety_zones = await spatial_queries.get_active_safety_zones(lat, lng, radius_m)
        closure_zones = await spatial_queries.get_active_closures(lat, lng, radius_m)
        
        import json as _json
        features = []
        for z in safety_zones:
            features.append({
                "type": "Feature",
                "geometry": _json.loads(z["geojson"]),
                "properties": {
                    "zone_type": "safety",
                    "source": z["source"],
                    "safety_score": z["safety_score"],
                }
            })
        for z in closure_zones:
            features.append({
                "type": "Feature",
                "geometry": _json.loads(z["geojson"]),
                "properties": {
                    "zone_type": "closure",
                    "source": z["source"],
                    "closure_type": z["closure_type"],
                    "description": z["description"],
                }
            })
        
        return {
            "type": "FeatureCollection",
            "features": features,
            "meta": {
                "safety_zone_count": len(safety_zones),
                "closure_zone_count": len(closure_zones),
                "radius_m": radius_m,
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
