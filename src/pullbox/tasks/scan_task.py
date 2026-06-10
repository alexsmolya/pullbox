"""History cleanup background task.

Scheduled task:
- ``cleanup_history`` (cron, default 05:00) — prunes old download history
  records that exceed the configured retention period.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import delete

from pullbox.config import get_settings
from pullbox.core.scheduler import scheduled_task
from pullbox.database import get_session_factory
from pullbox.models.download import DownloadHistory, DownloadState

logger = structlog.get_logger(__name__)


@scheduled_task(task_id="cleanup_history", trigger="cron", display_name="Cleanup History", hour=5)
async def cleanup_history() -> None:
    """Prune old download history records past the retention period."""
    settings = get_settings()
    factory = get_session_factory()

    cutoff = datetime.now(UTC) - timedelta(days=settings.history_retention_days)

    async with factory() as session:
        try:
            cursor = await session.execute(
                delete(DownloadHistory).where(
                    DownloadHistory.state.in_(
                        [
                            DownloadState.COMPLETED,
                            DownloadState.FAILED,
                        ]
                    ),
                    DownloadHistory.completed_at < cutoff,
                )
            )
            pruned: int = cursor.rowcount  # type: ignore[attr-defined]

            await session.commit()

            if pruned:
                logger.info(
                    "cleanup_history_complete",
                    pruned=pruned,
                    retention_days=settings.history_retention_days,
                )
        except Exception:
            await session.rollback()
            raise
