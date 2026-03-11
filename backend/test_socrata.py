import httpx
import asyncio

async def main():
    url = "https://data.cityofberkeley.info/resource/gnap-fj3t.json?$limit=5&$order=create_datetime DESC"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url)
        print("Status:", resp.status_code)
        if resp.status_code == 200:
            data = resp.json()
            for row in data:
                print(row)
        else:
            print("Response:", resp.text)

asyncio.run(main())
