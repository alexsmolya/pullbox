"""Thin scheduler wrappers for the download monitor and recovery sweep."""

from __future__ import annotations

from pullbox.core.scheduler import scheduled_task
from pullbox.tasks.download_task import monitor_downloads, process_completed


@scheduled_task(
    task_id="monitor_downloads",
    trigger="interval",
    display_name="Refresh Monitored Downloads",
    seconds=3,
)
async def scheduled_monitor_downloads() -> None:
    """Run the download monitor poller on its configured cadence."""
    await monitor_downloads()


@scheduled_task(
    task_id="process_completed",
    trigger="interval",
    display_name="Process Completed Downloads",
    seconds=300,
)
async def scheduled_process_completed() -> None:
    """Run the completed-download recovery sweep on its backstop cadence."""
    await process_completed()
