import httpx
import asyncio

async def main():
    # Test Berkeley AQI
    url = "https://air-quality-api.open-meteo.com/v1/air-quality?latitude=37.8715&longitude=-122.2730&current=us_aqi,pm10,pm2_5"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url)
        print("AQI Response:", resp.json())

    # Test Weather
    weather_url = "https://api.open-meteo.com/v1/forecast?latitude=37.8715&longitude=-122.2730&current=temperature_2m,precipitation,wind_speed_10m"
    async with httpx.AsyncClient() as client:
        w_resp = await client.get(weather_url)
        print("Weather Response:", w_resp.json())

    # Test Overpass for unlit streets
    overpass_url = "https://overpass-api.de/api/interpreter"
    query = """
    [out:json][timeout:15];
    way["highway"]["lit"="no"](37.85,-122.30, 37.89,-122.24);
    out geom;
    """
    async with httpx.AsyncClient() as client:
        o_resp = await client.post(overpass_url, data=query)
        data = o_resp.json()
        print(f"Found {len(data.get('elements', []))} unlit ways in Berkeley.")

asyncio.run(main())
