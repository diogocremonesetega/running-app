"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

# ── Expose full tracebacks for every logger in the app ──
# Without this, logger.exception() calls are silently dropped
# because no handler is attached to the root logger.
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s:%(lineno)d — %(message)s",
)

from app.routers import routes


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start background workers on startup."""
    from app.workers.data_ingest import start_background_workers
    await start_background_workers()
    yield


app = FastAPI(
    title="Running Route Generator",
    description="Elevation-aware running route generation with traffic signal avoidance",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS — allow all origins for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files for the visualizer
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Include routes
app.include_router(routes.router)


@app.get("/")
async def root():
    """Serve the elevation visualizer or show API info."""
    visualizer = os.path.join(static_dir, "index.html")
    if os.path.isfile(visualizer):
        return FileResponse(visualizer)
    return {
        "app": "Running Route Generator",
        "docs": "/docs",
        "health": "/api/v1/health",
    }
