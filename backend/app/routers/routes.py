"""API router for route generation endpoints."""

from __future__ import annotations

import logging
import uuid
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from geoalchemy2.shape import from_shape
from shapely.geometry import LineString

from app.db import get_db
from app.models.spatial import RouteHistory
from app.services import route_generator, graphhopper
from app.services.route_generator import InfrastructureFlags

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["routes"])


# --- Request / Response models ---

class Coordinate(BaseModel):
    lat: float = Field(..., ge=-90, le=90, description="Latitude")
    lng: float = Field(..., ge=-180, le=180, description="Longitude")


class RouteInfrastructureFlags(BaseModel):
    avoid_traffic_signals: bool = False
    prioritize_well_lit_streets: bool = False
    prioritize_soft_surfaces: bool = False
    include_water: bool = False
    include_restrooms: bool = False


class GenerateRouteRequest(RouteInfrastructureFlags):
    start: Coordinate
    distance_km: float = Field(5.0, gt=0.5, le=50, description="Target distance in km")
    elevation_preference: Literal["flat", "moderate", "hilly"] = "moderate"


class PointToPointRequest(RouteInfrastructureFlags):
    """Simple point-to-point route (no loop)."""
    start: Coordinate
    end: Coordinate
    elevation_preference: Literal["flat", "moderate", "hilly"] = "moderate"


def _to_infrastructure_flags(req: RouteInfrastructureFlags) -> InfrastructureFlags:
    return InfrastructureFlags(
        avoid_traffic_signals=req.avoid_traffic_signals,
        prioritize_well_lit_streets=req.prioritize_well_lit_streets,
        prioritize_soft_surfaces=req.prioritize_soft_surfaces,
        include_water=req.include_water,
        include_restrooms=req.include_restrooms,
    )


# --- Endpoints ---

@router.post("/generate-route")
async def generate_route(req: GenerateRouteRequest):
    """Generate an organic loop running route via GraphHopper's round_trip algorithm."""
    try:
        return await route_generator.generate_loop_route(
            start_lat=req.start.lat,
            start_lng=req.start.lng,
            distance_km=req.distance_km,
            elevation_preference=req.elevation_preference,
            avoid_traffic_signals=req.avoid_traffic_signals,
            prioritize_well_lit_streets=req.prioritize_well_lit_streets,
            prioritize_soft_surfaces=req.prioritize_soft_surfaces,
            include_water=req.include_water,
            include_restrooms=req.include_restrooms,
        )
    except graphhopper.GraphHopperError as e:
        status = 503 if e.status_code == 503 else 502
        logger.warning("GraphHopper error during route generation: %s", e.detail)
        raise HTTPException(status_code=status, detail=e.detail)
    except Exception as e:
        logger.exception("Unhandled exception in generate_route")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/point-to-point")
async def point_to_point_route(req: PointToPointRequest):
    """Generate a point-to-point route with elevation and infrastructure toggles."""
    try:
        return await route_generator.generate_point_to_point_route(
            start_lat=req.start.lat,
            start_lng=req.start.lng,
            end_lat=req.end.lat,
            end_lng=req.end.lng,
            elevation_preference=req.elevation_preference,
            flags=_to_infrastructure_flags(req),
        )
    except graphhopper.GraphHopperError as e:
        status = 503 if e.status_code == 503 else 502
        raise HTTPException(status_code=status, detail=e.detail)


@router.get("/geocode")
async def geocode(q: str, limit: int = 5):
    """Geocode an address/place name to coordinates using Nominatim."""
    if not q or len(q.strip()) < 2:
        return {"results": []}

    params = {
        "q": q,
        "format": "jsonv2",
        "limit": min(limit, 8),
        "addressdetails": 1,
        "viewbox": "-122.35,37.95,-122.15,37.83",
        "bounded": 0,
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
    """List available elevation routing profiles."""
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


# --- Run History ---

class RunSaveRequest(BaseModel):
    """Payload sent from the frontend after a live run is completed."""
    coordinates: List[List[float]] = Field(
        ..., description="List of [lng, lat] pairs recorded during the run"
    )
    distance_m: float = Field(..., ge=0, description="Total distance in metres")
    duration_s: int = Field(..., ge=0, description="Active run duration in seconds")
    elevation_gain_m: float = Field(0.0, ge=0, description="Total elevation gain in metres")
    profile_used: Optional[str] = Field(None, description="GraphHopper routing profile")
    session_id: Optional[str] = Field(None, description="Optional anonymous session UUID")


@router.post("/runs", status_code=201)
async def save_run(payload: RunSaveRequest, db: AsyncSession = Depends(get_db)):
    """Persist a completed live run to the route_history table."""
    if len(payload.coordinates) < 2:
        raise HTTPException(status_code=422, detail="A run must contain at least 2 GPS points.")

    try:
        user_uuid = uuid.UUID(payload.session_id) if payload.session_id else uuid.uuid4()
    except ValueError:
        user_uuid = uuid.uuid4()

    line = LineString([(c[0], c[1]) for c in payload.coordinates])

    run = RouteHistory(
        user_id=user_uuid,
        route_geom=from_shape(line, srid=4326),
        distance_m=payload.distance_m,
        duration_s=payload.duration_s,
        elevation_gain_m=payload.elevation_gain_m,
        profile_used=payload.profile_used,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    return {"id": str(run.id)}
