"""Blocklist maintenance task — expires old blocklist entries on a daily schedule."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import delete

from pullbox.core.config_resolver import get_int_setting, load_system_config_values
from pullbox.core.scheduler import scheduled_task
from pullbox.database import get_session_factory
from pullbox.models.blocklist import BlocklistEntry

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

_BLOCKLIST_EXPIRY_CONFIG_KEY = "blocklist.expiry_days"
_DEFAULT_BLOCKLIST_EXPIRY_DAYS = 90


async def cleanup_expired_blocklist(session: AsyncSession) -> int:
    """Remove blocklist entries older than the configured expiry period.

    Reads blocklist.expiry_days from SystemConfig (default 90).
    When set to 0, expiry is disabled and no entries are removed.

    Returns the number of entries removed.
    """
    configs = await load_system_config_values(session, (_BLOCKLIST_EXPIRY_CONFIG_KEY,))
    expiry_days = get_int_setting(
        configs,
        _BLOCKLIST_EXPIRY_CONFIG_KEY,
        _DEFAULT_BLOCKLIST_EXPIRY_DAYS,
    )

    if expiry_days <= 0:
        return 0

    cutoff = datetime.now(UTC) - timedelta(days=expiry_days)

    result = await session.execute(
        delete(BlocklistEntry).where(BlocklistEntry.created_at <= cutoff)
    )
    removed: int = result.rowcount  # type: ignore[attr-defined]

    if removed > 0:
        logger.info(
            "blocklist_expired_entries_removed",
            count=removed,
            cutoff_days=expiry_days,
        )

    return removed


@scheduled_task(
    task_id="expire_blocklist",
    trigger="cron",
    display_name="Expire Blocklist",
    hour=6,
    minute=30,
)
async def expire_blocklist_entries() -> int:
    """Scheduled wrapper — creates a session and calls cleanup_expired_blocklist."""
    factory = get_session_factory()

    async with factory() as session:
        try:
            count = await cleanup_expired_blocklist(session)
            await session.commit()
            return count
        except Exception:
            await session.rollback()
            logger.exception("blocklist_expiry_task_failed")
            raise
