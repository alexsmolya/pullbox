"""Thin scheduler wrappers for wanted searches and search-log retention."""

from __future__ import annotations

from pullbox.core.scheduler import TaskExecutionResult, scheduled_task
from pullbox.tasks.search_task import purge_search_logs, search_wanted


@scheduled_task(
    task_id="search_wanted",
    trigger="interval",
    display_name="Search Wanted",
    hours=6,
)
async def scheduled_search_wanted() -> TaskExecutionResult:
    """Run the wanted-issue search sweep on its configured cadence."""
    return await search_wanted()


@scheduled_task(
    task_id="purge_search_logs",
    trigger="cron",
    display_name="Purge Search Logs",
    hour=4,
)
async def scheduled_purge_search_logs() -> None:
    """Run the search-log retention cleanup on its nightly cadence."""
    await purge_search_logs()
