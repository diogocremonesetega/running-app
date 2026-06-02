import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from app.services import osm_infrastructure, route_generator


@pytest.mark.asyncio
async def test_unlit_street_boxes():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "elements": [
            {
                "type": "way",
                "bounds": {
                    "minlat": 37.87,
                    "minlon": -122.26,
                    "maxlat": 37.88,
                    "maxlon": -122.25,
                },
            }
        ]
    }

    mock_client_instance = MagicMock()
    mock_client_instance.post = AsyncMock(return_value=mock_resp)

    class MockAsyncClient:
        async def __aenter__(self):
            return mock_client_instance

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    with patch("app.services.osm_infrastructure.httpx.AsyncClient", return_value=MockAsyncClient()):
        zones = await osm_infrastructure.fetch_unlit_street_boxes("37.8,-122.3,37.9,-122.2")
        assert len(zones) == 1
        assert zones[0]["min_lat"] == 37.87


@pytest.mark.asyncio
async def test_water_points_from_nodes():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "elements": [{"type": "node", "lat": 37.87, "lon": -122.26}]
    }

    mock_client_instance = MagicMock()
    mock_client_instance.post = AsyncMock(return_value=mock_resp)

    class MockAsyncClient:
        async def __aenter__(self):
            return mock_client_instance

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    with patch("app.services.osm_infrastructure.httpx.AsyncClient", return_value=MockAsyncClient()):
        zones = await osm_infrastructure.fetch_water_points("37.8,-122.3,37.9,-122.2")
        assert len(zones) == 1
        assert zones[0]["min_lat"] < zones[0]["max_lat"]


def test_infrastructure_flags_dataclass():
    flags = route_generator.InfrastructureFlags(include_water=True, include_restrooms=True)
    assert flags.include_water is True
    assert flags.include_restrooms is True
