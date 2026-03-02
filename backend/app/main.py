"""FastAPI application entry point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

from app.routers import routes

app = FastAPI(
    title="Running Route Generator",
    description="Elevation-aware running route generation with traffic signal avoidance",
    version="0.1.0",
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
