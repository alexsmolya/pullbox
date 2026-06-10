"""Intervention queue maintenance task.

Scheduled task that expires stale pending matches older than the
configured threshold (default: 30 days).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from pullbox.core.config_resolver import get_int_setting, load_system_config_values
from pullbox.core.scheduler import scheduled_task
from pullbox.database import get_session_factory
from pullbox.services.intervention_service import InterventionService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

_EXPIRY_CONFIG_KEY = "search_intervention_expiry_days"
_DEFAULT_EXPIRY_DAYS = 10


async def _run_expiry(session: AsyncSession) -> int:
    """Run expiry logic against the given session. Returns count expired."""
    configs = await load_system_config_values(session, (_EXPIRY_CONFIG_KEY,))
    max_age_days = get_int_setting(configs, _EXPIRY_CONFIG_KEY, _DEFAULT_EXPIRY_DAYS)

    svc = InterventionService()
    return await svc.expire_stale(session, max_age_days)


@scheduled_task(
    task_id="expire_pending_matches",
    trigger="cron",
    display_name="Expire Pending Matches",
    hour=6,
)
async def expire_pending_matches() -> None:
    """Expire stale pending matches past the configured threshold."""
    factory = get_session_factory()

    async with factory() as session:
        try:
            count = await _run_expiry(session)
            await session.commit()
            if count:
                logger.info("expire_pending_matches_complete", expired=count)
        except Exception:
            await session.rollback()
            raise
