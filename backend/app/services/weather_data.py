import logging
import httpx
import time
import asyncio
from typing import Dict, Any

logger = logging.getLogger(__name__)

# Simple in-memory cache for weather data
_cache: Dict[str, Dict[str, Any]] = {}
CACHE_TTL_SECONDS = 1800  # 30 minutes

async def fetch_current_conditions(lat: float, lng: float) -> Dict[str, Any]:
    """Fetch current weather and AQI for a given location using Open-Meteo.
    
    Rounds coordinates to 2 decimal places (approx 1.1km) for cache keys.
    """
    global _cache
    
    # Round to 2 decimal places to cluster nearby requests
    cache_key = f"{round(lat, 2)},{round(lng, 2)}"
    now = time.time()
    
    if cache_key in _cache:
        cached_entry = _cache[cache_key]
        if (now - cached_entry["last_fetched"]) < CACHE_TTL_SECONDS:
            logger.info("Using cached weather data")
            return cached_entry["data"]

    logger.info(f"Fetching live weather/AQI for {cache_key}...")
    
    # We must make two separate requests as Open-Meteo splits weather and air quality
    weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lng}&current=temperature_2m,precipitation,wind_speed_10m"
    aqi_url = f"https://air-quality-api.open-meteo.com/v1/air-quality?latitude={lat}&longitude={lng}&current=us_aqi"

    result = {
        "temperature_c": None,
        "precipitation_mm": 0.0,
        "us_aqi": None,
        "aqi_warning": False,
        "weather_warning": False
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            w_resp, a_resp = await asyncio.gather(
                client.get(weather_url),
                client.get(aqi_url),
                return_exceptions=True
            )

            if hasattr(w_resp, "status_code") and getattr(w_resp, "status_code") == 200:
                w_data = getattr(w_resp, "json")().get("current", {})
                result["temperature_c"] = w_data.get("temperature_2m")
                precip = w_data.get("precipitation", 0.0)
                result["precipitation_mm"] = precip if precip is not None else 0.0
                
                # Warn if heavy rain or extreme temps
                temp = result["temperature_c"]
                if result["precipitation_mm"] > 5.0 or (temp is not None and (float(temp) > 35 or float(temp) < -5)):
                    result["weather_warning"] = True

            if hasattr(a_resp, "status_code") and getattr(a_resp, "status_code") == 200:
                a_data = getattr(a_resp, "json")().get("current", {})
                aqi = a_data.get("us_aqi")
                result["us_aqi"] = aqi
                
                # Warn if AQI > 100 (Unhealthy for Sensitive Groups)
                if aqi is not None and float(aqi) > 100:
                    result["aqi_warning"] = True

        _cache[cache_key] = {
            "data": result,
            "last_fetched": now
        }
        return result

    except Exception as e:
        logger.error(f"Failed to fetch environmental data: {e}")
        return result
