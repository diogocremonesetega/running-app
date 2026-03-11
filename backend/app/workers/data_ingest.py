"""Background data ingestion workers.

Started on FastAPI application startup. Periodically refreshes safety
and closure zones so route generation always uses fresh PostGIS data.
"""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

logger = logging.getLogger(__name__)

# Default refresh interval in seconds (30 minutes)
DEFAULT_INTERVAL = 1800


async def _run_periodic(task_fn: Callable[[], Coroutine[Any, Any, int]], interval: int, name: str) -> None:
    """Run `task_fn` immediately, then repeat every `interval` seconds."""
    while True:
        try:
            count = await task_fn()
            logger.info(f"[{name}] refreshed {count} zones.")
        except Exception as exc:
            logger.error(f"[{name}] refresh failed: {exc}")
        await asyncio.sleep(interval)


async def start_background_workers() -> None:
    """Schedule all background refresh tasks.

    Called from the FastAPI lifespan startup event. Each worker runs
    as an independent asyncio Task so failures are isolated.
    """
    from app.services.crime import refresh_safety_zones
    from app.services.construction import refresh_closure_zones
    from app.services.scenic import refresh_scenic_segments

    asyncio.create_task(
        _run_periodic(refresh_safety_zones, DEFAULT_INTERVAL, "safety_zones"),
        name="refresh_safety_zones",
    )
    asyncio.create_task(
        _run_periodic(refresh_closure_zones, DEFAULT_INTERVAL, "closure_zones"),
        name="refresh_closure_zones",
    )
    # Scenic data changes slowly — refresh every 6 hours
    asyncio.create_task(
        _run_periodic(refresh_scenic_segments, 6 * 3600, "scenic_segments"),
        name="refresh_scenic_segments",
    )
    logger.info("Background data ingestion workers started.")
