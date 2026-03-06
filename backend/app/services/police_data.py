import json
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)

async def fetch_safety_data() -> List[Dict[str, float]]:
    """Fetch 'Calls for Service' or crime data for Berkeley.
    
    Returns a list of incident coordinates and weights:
        [{'lat': 37.866, 'lng': -122.258, 'weight': 1.0}, ...]
        
    Note: Replaced with simulated high-incident areas in Berkeley for the 
    prototype. In a full production setup, this would query the City of 
    Berkeley Open Data portal (e.g. Socrata / OData API) and cache the response.
    """
    mock_data = [
        # Southside / Telegraph area (Simulated hot zone)
        {"lat": 37.866, "lng": -122.258, "weight": 1.0},
        {"lat": 37.865, "lng": -122.259, "weight": 0.9},
        {"lat": 37.867, "lng": -122.258, "weight": 0.8},
        {"lat": 37.8655, "lng": -122.2585, "weight": 0.7},
        
        # Downtown Berkeley (Simulated hot zone)
        {"lat": 37.871, "lng": -122.268, "weight": 0.85},
        {"lat": 37.870, "lng": -122.269, "weight": 0.75},
        {"lat": 37.872, "lng": -122.267, "weight": 0.6},
        {"lat": 37.8715, "lng": -122.2685, "weight": 0.8},
        
        # West Berkeley / San Pablo Park area
        {"lat": 37.855, "lng": -122.283, "weight": 0.7},
        {"lat": 37.856, "lng": -122.284, "weight": 0.65},
        {"lat": 37.854, "lng": -122.282, "weight": 0.5},
    ]
    return mock_data

def get_danger_zones(incidents: List[Dict[str, float]], radius_deg: float = 0.002) -> List[Dict[str, float]]:
    """Convert incident points into bounding boxes for GraphHopper custom areas.
    
    Groups incidents into simple bounding boxes to avoid in the routing engine.
    """
    # For the prototype, we just draw a small box around the highest weight incidents.
    zones = []
    for inc in incidents:
        if inc["weight"] >= 0.7:
            zones.append({
                "min_lat": inc["lat"] - radius_deg,
                "max_lat": inc["lat"] + radius_deg,
                "min_lng": inc["lng"] - radius_deg,
                "max_lng": inc["lng"] + radius_deg,
            })
    return zones
