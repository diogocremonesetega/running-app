"""Weather and environmental conditions with Run Comfort Score.

Fetches temperature, precipitation, wind speed/direction, and AQI
from Open-Meteo (no API key required). Computes a Run Comfort Score
and suggests an optimal start bearing based on wind direction.
"""

import asyncio
import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_cache: dict[str, dict[str, Any]] = {}
CACHE_TTL_SECONDS = 1800  # 30 minutes


def _compute_comfort_score(temperature_c: float | None, precipitation_mm: float,
                            wind_speed_kmh: float, us_aqi: float | None) -> int:
    """Compute a Run Comfort Score from 0-100.

    Deductions:
      -30  heavy rain (precip > 2mm)
      -20  bad air quality (AQI > 100)
      -10  strong wind (wind_speed > 30 km/h)
      -15  extreme cold (< 0°C) or heat (> 32°C)
    """
    score = 100
    if precipitation_mm > 2.0:
        score -= 30
    elif precipitation_mm > 0.5:
        score -= 10
    if us_aqi is not None and float(us_aqi) > 100:
        score -= 20
    if wind_speed_kmh > 30:
        score -= 10
    elif wind_speed_kmh > 50:
        score -= 20  # cumulative
    if temperature_c is not None:
        t = float(temperature_c)
        if t < 0 or t > 32:
            score -= 15
    return max(0, min(100, score))


def _optimal_bearing(wind_direction_deg: float) -> float:
    """Suggest start bearing so runner runs INTO the wind first.

    When the route begins into the wind, the return leg has a tailwind —
    a classic distance runner's strategy.
    """
    return (wind_direction_deg + 180) % 360


def _comfort_label(score: int) -> str:
    if score >= 80:
        return "Excellent"
    elif score >= 60:
        return "Good"
    elif score >= 40:
        return "Fair"
    else:
        return "Poor"


async def fetch_current_conditions(lat: float, lng: float) -> dict[str, Any]:
    """Fetch weather + AQI for a location. Returns comfort score and wind data.

    Caches results for 30 minutes keyed by rounded coordinates.
    """
    cache_key = f"{round(lat, 2)},{round(lng, 2)}"
    now = time.time()

    if cache_key in _cache and (now - _cache[cache_key]["last_fetched"]) < CACHE_TTL_SECONDS:
        logger.info("Using cached weather data")
        return _cache[cache_key]["data"]

    logger.info(f"Fetching live weather/AQI for {cache_key}...")

    weather_url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lng}"
        f"&current=temperature_2m,precipitation,wind_speed_10m,wind_direction_10m"
    )
    aqi_url = (
        f"https://air-quality-api.open-meteo.com/v1/air-quality"
        f"?latitude={lat}&longitude={lng}&current=us_aqi"
    )

    result: dict[str, Any] = {
        "temperature_c": None,
        "precipitation_mm": 0.0,
        "wind_speed_kmh": 0.0,
        "wind_direction_deg": 0.0,
        "us_aqi": None,
        "comfort_score": 100,
        "comfort_label": "Excellent",
        "optimal_start_bearing": 0.0,
        "aqi_warning": False,
        "weather_warning": False,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            w_resp, a_resp = await asyncio.gather(
                client.get(weather_url),
                client.get(aqi_url),
                return_exceptions=True,
            )

        if hasattr(w_resp, "status_code") and w_resp.status_code == 200:
            w = w_resp.json().get("current", {})
            result["temperature_c"] = w.get("temperature_2m")
            result["precipitation_mm"] = float(w.get("precipitation") or 0.0)
            result["wind_speed_kmh"] = float(w.get("wind_speed_10m") or 0.0)
            result["wind_direction_deg"] = float(w.get("wind_direction_10m") or 0.0)

            temp = result["temperature_c"]
            if result["precipitation_mm"] > 5.0 or (temp is not None and (float(temp) > 35 or float(temp) < -5)):
                result["weather_warning"] = True

        if hasattr(a_resp, "status_code") and a_resp.status_code == 200:
            aqi = a_resp.json().get("current", {}).get("us_aqi")
            result["us_aqi"] = aqi
            if aqi is not None and float(aqi) > 100:
                result["aqi_warning"] = True

        comfort = _compute_comfort_score(
            temperature_c=result["temperature_c"],
            precipitation_mm=result["precipitation_mm"],
            wind_speed_kmh=result["wind_speed_kmh"],
            us_aqi=result["us_aqi"],
        )
        result["comfort_score"] = comfort
        result["comfort_label"] = _comfort_label(comfort)
        result["optimal_start_bearing"] = _optimal_bearing(result["wind_direction_deg"])

        _cache[cache_key] = {"data": result, "last_fetched": now}

    except Exception as exc:
        logger.error(f"Failed to fetch environmental data: {exc}")

    return result
