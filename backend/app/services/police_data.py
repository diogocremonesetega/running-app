import json
import logging
from typing import List, Dict, Any

import httpx
import time
import asyncio

logger = logging.getLogger(__name__)

# Simple in-memory cache
_cache: Dict[str, Any] = {
    "data": [],
    "last_fetched": 0.0
}
CACHE_TTL_SECONDS = 3600  # 1 hour

async def fetch_safety_data() -> List[Dict[str, float]]:
    """Fetch 'Calls for Service' or crime data for Berkeley from Socrata API.
    
    Returns a list of incident coordinates and weights:
        [{'lat': 37.866, 'lng': -122.258, 'weight': 1.0}, ...]
    """
    global _cache
    
    now = time.time()
    if _cache["data"] and (now - _cache["last_fetched"]) < CACHE_TTL_SECONDS:
        logger.info("Using cached Berkeley Police data")
        return _cache["data"]
        
    logger.info("Fetching live Berkeley Police data from Socrata API...")
    url = "https://data.cityofberkeley.info/resource/k2nh-s5h5.json?$limit=500&$order=eventdt DESC"
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            raw_data = resp.json()
            
        processed_data = []
        for row in raw_data:
            lat = row.get("block_location", {}).get("latitude")
            lng = row.get("block_location", {}).get("longitude")
            
            if not lat or not lng:
                continue
                
            cvlegend = row.get("cvlegend", "").upper()
            
            # Weighting by severity (arbitrary for prototype)
            weight = 0.5
            if "ROBBERY" in cvlegend or "ASSAULT" in cvlegend or "WEAPON" in cvlegend:
                weight = 1.0
            elif "BURGLARY" in cvlegend or "THEFT" in cvlegend or "LARCENY" in cvlegend:
                weight = 0.8
            elif "VANDALISM" in cvlegend:
                weight = 0.6
                
            processed_data.append({
                "lat": float(lat),
                "lng": float(lng),
                "weight": weight
            })
            
        _cache["data"] = processed_data
        _cache["last_fetched"] = now
        logger.info(f"Successfully fetched and cached {len(processed_data)} incidents.")
        return processed_data
        
    except Exception as e:
        logger.error(f"Failed to fetch Berkeley Police data: {e}")
        # Return whatever is in cache if it failed, else empty list
        return _cache["data"]

def get_danger_zones(incidents: List[Dict[str, float]], radius_deg: float = 0.0008) -> List[Dict[str, float]]:
    """Convert incident points into bounding boxes for GraphHopper custom areas.
    
    Groups incidents into simple bounding boxes to avoid in the routing engine.
    Reduced radius to keep zones tight and prevent massive route detours.
    """
    # To avoid creating too many boxes and ruining routes, we only create them 
    # for the highest severity incidents (weight == 1.0)
    zones = []
    for inc in incidents:
        if inc["weight"] >= 1.0:
            zones.append({
                "min_lat": inc["lat"] - radius_deg,
                "max_lat": inc["lat"] + radius_deg,
                "min_lng": inc["lng"] - radius_deg,
                "max_lng": inc["lng"] + radius_deg,
            })
    return zones
