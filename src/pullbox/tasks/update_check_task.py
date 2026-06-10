"""Scheduled task — daily update check against GitHub releases."""

from __future__ import annotations

import structlog

from pullbox.core.scheduler import scheduled_task

logger = structlog.get_logger(__name__)


@scheduled_task(
    task_id="check_for_updates",
    trigger="cron",
    display_name="Update Check",
    hour=6,
    minute=0,
    misfire_grace_time=3600,
)
async def check_for_updates() -> None:
    """Check GitHub releases for a newer version (runs daily at 6 AM)."""
    from pullbox.app import get_update_check_service
    from pullbox.services.update_check import UpdateCheckService

    service = get_update_check_service()
    if not isinstance(service, UpdateCheckService):
        logger.debug("update_check_skipped", reason="service not initialized")
        return

    result = await service.check_for_update(force=True)
    if result and result.update_available:
        logger.info(
            "update_available",
            current=result.current_version,
            latest=result.latest_version,
            url=result.release_url,
        )
    elif result:
        logger.debug("update_check_current", version=result.current_version)
    else:
        logger.warning("update_check_failed", reason="service returned no result")
