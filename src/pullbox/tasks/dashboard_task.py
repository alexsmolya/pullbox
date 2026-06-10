"""Dashboard intelligence task — refreshes rollups for the executive dashboard."""

from __future__ import annotations

import asyncio

import structlog
from sqlalchemy.exc import OperationalError

from pullbox.core.scheduler import scheduled_task
from pullbox.core.sqlite_lock import (
    SQLITE_LOCK_RETRY_ATTEMPTS,
    is_sqlite_locked_error,
    sqlite_lock_retry_delay,
)
from pullbox.database import get_session_factory
from pullbox.services.dashboard_intelligence_service import DashboardIntelligenceService

logger = structlog.get_logger(__name__)


@scheduled_task(
    task_id="refresh_dashboard_intelligence",
    trigger="interval",
    display_name="Refresh Dashboard Intelligence",
    hours=1,
    misfire_grace_time=3600,
)
async def refresh_dashboard_intelligence() -> None:
    """Recompute and persist dashboard rollups for trend and runway calculations."""
    factory = get_session_factory()
    for attempt in range(1, SQLITE_LOCK_RETRY_ATTEMPTS + 1):
        async with factory() as session:
            try:
                service = DashboardIntelligenceService(session)
                await service.capture_rollups()
                await session.commit()
                return
            except OperationalError as exc:
                await session.rollback()
                if not is_sqlite_locked_error(exc) or attempt == SQLITE_LOCK_RETRY_ATTEMPTS:
                    raise
                delay_seconds = sqlite_lock_retry_delay(attempt)
                logger.warning(
                    "dashboard_rollup_retrying_after_sqlite_lock",
                    attempt=attempt,
                    max_attempts=SQLITE_LOCK_RETRY_ATTEMPTS,
                    delay_seconds=delay_seconds,
                )
        await asyncio.sleep(delay_seconds)
