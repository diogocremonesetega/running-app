import logging
import httpx
from typing import List, Dict

logger = logging.getLogger(__name__)

async def fetch_unlit_streets(bbox: str) -> List[Dict[str, float]]:
    """Fetch unlit streets from OpenStreetMap via Overpass API within a bounding box.
    
    Args:
        bbox: String format "south,west,north,east"
        
    Returns:
        List of bounding boxes for unlit street segments to avoid.
    """
    logger.info(f"Fetching unlit streets for bbox: {bbox}")
    
    query = f"""
    [out:json][timeout:15];
    way["highway"]["lit"="no"]({bbox});
    out bb;
    """
    
    url = "https://overpass-api.de/api/interpreter"
    zones = []
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, data=query)
            resp.raise_for_status()
            data = resp.json()
            
            elements = data.get("elements", [])
            for el in elements:
                bounds = el.get("bounds")
                if bounds:
                    zones.append({
                        "min_lat": bounds["minlat"],
                        "max_lat": bounds["maxlat"],
                        "min_lng": bounds["minlon"],
                        "max_lng": bounds["maxlon"],
                    })
                    
            logger.info(f"Found {len(zones)} unlit street zones.")
            return zones
    except Exception as e:
        logger.error(f"Failed to fetch unlit streets from Overpass: {e}")
        return zones
