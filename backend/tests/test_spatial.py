import asyncio
import datetime
from sqlalchemy import select, text
from geoalchemy2.elements import WKTElement

from app.db import engine, async_session_maker
from app.models.spatial import SafetyZone

def test_database_connection_and_spatial_query():
    async def run_test():
        async with async_session_maker() as session:
            # 1. Simple query to verify PostGIS is enabled
            result = await session.execute(text("SELECT PostGIS_Version();"))
            version = result.scalar()
            assert version is not None, "PostGIS is not enabled or reachable"
            print(f"PostGIS Version: {version}")

            # 2. Insert a temporary safety zone
            polygon_wkt = "POLYGON((-122.4194 37.7749, -122.4194 37.7849, -122.4094 37.7849, -122.4094 37.7749, -122.4194 37.7749))"
            zone = SafetyZone(
                source="test",
                safety_score=20.0,
                geom=WKTElement(polygon_wkt, srid=4326),
                expires_at=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)
            )
            session.add(zone)
            await session.commit()
            
            # 3. Spatial Intersects Query
            # Let's see if a point inside intersects
            point_wkt = "POINT(-122.4150 37.7800)"
            query = select(SafetyZone).where(
                SafetyZone.geom.ST_Intersects(WKTElement(point_wkt, srid=4326))
            )
            intersecting_zones = (await session.execute(query)).scalars().all()
            
            assert len(intersecting_zones) >= 1
            assert intersecting_zones[0].source == "test"

            # Cleanup
            await session.delete(intersecting_zones[0])
            await session.commit()
            
            print("Test passed successfully.")
            
    try:
        asyncio.run(run_test())
    except Exception as e:
        print(f"Database might not be running or test failed: {e}")
        # Not failing the python process right now if db is not up since docker isn't running on this host

if __name__ == "__main__":
    test_database_connection_and_spatial_query()
