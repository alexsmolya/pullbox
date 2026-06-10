"""Thin scheduler wrappers for metadata refresh and new-issue sync."""

from __future__ import annotations

from pullbox.core.scheduler import scheduled_task
from pullbox.tasks.metadata_task import refresh_metadata, sync_new_issues


@scheduled_task(
    task_id="sync_new_issues",
    trigger="interval",
    display_name="Sync New Issues",
    hours=24,
)
async def scheduled_sync_new_issues() -> None:
    """Run the monitored-series issue sync on its configured cadence."""
    await sync_new_issues()


@scheduled_task(
    task_id="refresh_metadata",
    trigger="cron",
    display_name="Refresh Metadata",
    hour=3,
)
async def scheduled_refresh_metadata() -> None:
    """Run the stale-series metadata refresh on its nightly cadence."""
    await refresh_metadata()
