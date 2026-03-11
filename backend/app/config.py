"""Configuration loaded from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings, read from .env or environment."""

    graphhopper_url: str = "http://localhost:8989"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    debug: bool = True
    
    # PostGIS database URL
    database_url: str = "postgresql+asyncpg://routegen:securepassword@localhost:5432/routegen_db"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
