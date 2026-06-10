"""Helpers for temporary debug-logging overrides and expiry enforcement."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import delete as sa_delete
from sqlalchemy import select

from pullbox.database import get_session_factory
from pullbox.logging import reconfigure_logging_runtime
from pullbox.models.config import SystemConfig

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

DEBUG_LOGGING_OVERRIDE_KEYS = (
    "log_level_override",
    "log_level_override_expires",
    "log_level_base",
)


async def load_debug_logging_override(
    session: AsyncSession,
) -> dict[str, str]:
    """Return stored debug-logging override fields from ``system_config``."""
    result = await session.execute(
        select(SystemConfig).where(SystemConfig.key.in_(DEBUG_LOGGING_OVERRIDE_KEYS))
    )
    return {row.key: row.value for row in result.scalars().all()}


async def clear_debug_logging_override(
    session: AsyncSession,
) -> None:
    """Delete any stored debug-logging override rows."""
    await session.execute(
        sa_delete(SystemConfig).where(SystemConfig.key.in_(DEBUG_LOGGING_OVERRIDE_KEYS))
    )
    await session.commit()


async def expire_debug_logging_override_if_needed(
    session: AsyncSession,
    *,
    source: str,
) -> bool:
    """Clear an expired debug-logging override and revert the runtime level."""
    overrides = await load_debug_logging_override(session)
    if "log_level_override" not in overrides:
        return False

    expires_str = overrides.get("log_level_override_expires")
    if not expires_str:
        return False

    expires_at = datetime.fromisoformat(expires_str)
    if datetime.now(UTC) < expires_at:
        return False

    base_level = overrides.get("log_level_base", "info")
    await clear_debug_logging_override(session)
    reconfigure_logging_runtime(log_level=base_level)
    logger.info(
        "debug_logging_expired",
        reverted_to=base_level,
        source=source,
    )
    return True


async def restore_debug_logging_override_on_startup() -> None:
    """Resume an active override after restart, or clear it if already expired."""
    factory = get_session_factory()
    async with factory() as session:
        expired = await expire_debug_logging_override_if_needed(session, source="startup")
        if expired:
            return

        overrides = await load_debug_logging_override(session)

    if "log_level_override" not in overrides:
        return

    override_level = overrides["log_level_override"]
    expires_str = overrides.get("log_level_override_expires")
    reconfigure_logging_runtime(log_level=override_level)
    logger.info(
        "debug_logging_resumed_on_startup",
        level=override_level,
        expires_at=expires_str,
    )
