import pytest
from unittest.mock import patch, MagicMock
from app.services import weather_data, lighting_data, route_generator
from app.routers.routes import GenerateRouteRequest, Coordinate
import httpx
import logging

# Disable logging for tests
logging.getLogger("app.services.weather_data").setLevel(logging.CRITICAL)

from unittest.mock import patch, MagicMock, AsyncMock

@pytest.mark.asyncio
async def test_aqi_alert_warning():
    """Test that warning flag is set when AQI is high."""
    lat, lng = 37.87, -122.25
    
    mock_weather_resp = MagicMock()
    mock_weather_resp.status_code = 200
    mock_weather_resp.json.return_value = {
        "current": {"temperature_2m": 20.0, "precipitation": 0.0}
    }
    
    mock_aqi_resp = MagicMock()
    mock_aqi_resp.status_code = 200
    mock_aqi_resp.json.return_value = {
        "current": {"us_aqi": 150} # High AQI!
    }

    async def mock_gather(*args, **kwargs):
        return [mock_weather_resp, mock_aqi_resp]

    with patch("app.services.weather_data.asyncio.gather", new=mock_gather):
        weather_data._cache.clear()
        
        result = await weather_data.fetch_current_conditions(lat, lng)
        assert result["aqi_warning"] is True
        assert result["us_aqi"] == 150

@pytest.mark.asyncio
async def test_heavy_rain_warning():
    """Test that warning flag is set for heavy precipitation."""
    lat, lng = 37.87, -122.25
    
    mock_weather_resp = MagicMock()
    mock_weather_resp.status_code = 200
    mock_weather_resp.json.return_value = {
        "current": {"temperature_2m": 15.0, "precipitation": 12.0} # Heavy Rain
    }
    mock_aqi_resp = MagicMock()
    mock_aqi_resp.status_code = 200
    mock_aqi_resp.json.return_value = {"current": {"us_aqi": 30}}

    async def mock_gather(*args, **kwargs):
        return [mock_weather_resp, mock_aqi_resp]

    with patch("app.services.weather_data.asyncio.gather", new=mock_gather):
        weather_data._cache.clear()
        result = await weather_data.fetch_current_conditions(lat, lng)
        assert result["weather_warning"] is True
        assert result["precipitation_mm"] == 12.0

@pytest.mark.asyncio
async def test_unlit_streets_fetching():
    """Test that Overpass parsing returns the correct bounding boxes."""
    # Mock Overpass response
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "elements": [
            {
                "type": "way",
                "id": 12345,
                "bounds": {
                    "minlat": 37.87,
                    "minlon": -122.26,
                    "maxlat": 37.88,
                    "maxlon": -122.25
                }
            }
        ]
    }
    
    mock_client_instance = MagicMock()
    mock_client_instance.post = AsyncMock(return_value=mock_resp)
    
    # Needs to mock async context manager for httpx.AsyncClient
    class MockAsyncClient:
        async def __aenter__(self):
            return mock_client_instance
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    with patch("app.services.lighting_data.httpx.AsyncClient", return_value=MockAsyncClient()):
        zones = await lighting_data.fetch_unlit_streets("37.8,-122.3,37.9,-122.2")
        assert len(zones) == 1
        assert zones[0]["min_lat"] == 37.87
        assert zones[0]["max_lng"] == -122.25
