from datetime import datetime
import uuid

from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from geoalchemy2 import Geometry

from app.db import Base


class SafetyZone(Base):
    __tablename__ = "safety_zones"

    id = Column(Integer, primary_key=True, index=True)
    source = Column(String(50), nullable=False)  # 'crimeometer', 'user_report'
    safety_score = Column(Float, nullable=False) # 0-100 (0 = dangerous, 100 = safe)
    geom = Column(Geometry('POLYGON', srid=4326), nullable=False) # WGS84 polygon
    fetched_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index('idx_safety_zones_geom', 'geom', postgresql_using='gist'),
    )


class ClosureZone(Base):
    __tablename__ = "closure_zones"

    id = Column(Integer, primary_key=True, index=True)
    source = Column(String(50), nullable=False)  # 'waze_cifs', 'wzdx', 'manual'
    closure_type = Column(String(100), nullable=True) # 'road_closure', 'construction', 'event'
    description = Column(String, nullable=True)
    geom = Column(Geometry('POLYGON', srid=4326), nullable=False)
    start_time = Column(DateTime(timezone=True))
    end_time = Column(DateTime(timezone=True))
    fetched_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index('idx_closure_zones_geom', 'geom', postgresql_using='gist'),
    )


class ScenicSegment(Base):
    __tablename__ = "scenic_segments"

    id = Column(Integer, primary_key=True, index=True)
    gvi_score = Column(Float, nullable=True) # Green View Index 0.0-1.0
    park_coverage = Column(Float, nullable=True) # % of segment near park
    geom = Column(Geometry('LINESTRING', srid=4326), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index('idx_scenic_segments_geom', 'geom', postgresql_using='gist'),
    )


class RouteHistory(Base):
    __tablename__ = "route_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    route_geom = Column(Geometry('LINESTRING', srid=4326))
    distance_m = Column(Float, nullable=True)
    elevation_gain_m = Column(Float, nullable=True)
    duration_s = Column(Integer, nullable=True)
    profile_used = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
