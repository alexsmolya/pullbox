"""Scheduled task wrapper for What's New cache refresh."""

from __future__ import annotations

from pullbox.core.scheduler import scheduled_task
from pullbox.services.whats_new_refresh_queue import run_whats_new_refresh


@scheduled_task(
    task_id="refresh_whats_new_cache",
    trigger="cron",
    display_name="Refresh What's New Cache",
    hour=7,
    minute=0,
    misfire_grace_time=3600,
    exclusive=True,
)
async def refresh_whats_new_cache() -> None:
    """Refresh cached pullbox-data release payloads on the daily cadence."""
    await run_whats_new_refresh()
