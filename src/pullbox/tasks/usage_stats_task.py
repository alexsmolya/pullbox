"""Scheduled task wrapper for anonymous usage-stats telemetry."""

from __future__ import annotations

from pullbox.core.scheduler import scheduled_task
from pullbox.services.usage_stats_telemetry import send_usage_stats_ping


@scheduled_task(
    task_id="send_usage_stats",
    trigger="cron",
    display_name="Send Anonymous Usage Stats",
    hour=8,
    minute=0,
    misfire_grace_time=3600,
    exclusive=True,
)
async def send_usage_stats() -> None:
    """Send daily anonymous usage stats when consent is enabled."""
    await send_usage_stats_ping()
