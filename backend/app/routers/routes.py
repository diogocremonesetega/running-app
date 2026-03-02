"""API router for route generation endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Literal

from app.services import route_generator, graphhopper

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
    num_waypoints: int = Field(5, ge=3, le=12, description="Circle waypoints")
    start_bearing: float = Field(0.0, ge=0, lt=360, description="Initial bearing offset")


class PointToPointRequest(BaseModel):
    """Simple point-to-point route (no loop)."""
    start: Coordinate
    end: Coordinate
    elevation_preference: Literal["flat", "moderate", "hilly"] = "moderate"
    avoid_traffic_signals: bool = False


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
            num_waypoints=req.num_waypoints,
            start_bearing=req.start_bearing,
        )
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
            "slope_segments": slope_segments,
        }
    except graphhopper.GraphHopperError as e:
        raise HTTPException(status_code=502, detail=f"GraphHopper error: {e.detail}")


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
