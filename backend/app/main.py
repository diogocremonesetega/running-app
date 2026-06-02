"""FastAPI application entry point."""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)

from app.routers import routes
from app.routers import diagnostics


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="Running Route Generator",
    description="Elevation-aware running routes with infrastructure preferences",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

app.include_router(routes.router)
app.include_router(diagnostics.router)


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
