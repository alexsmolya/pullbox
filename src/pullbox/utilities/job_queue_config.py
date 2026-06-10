"""Configuration helpers for utility job queue execution."""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import select

from pullbox.models.config import DEFAULT_SYSTEM_CONFIG, SystemConfig

logger = structlog.get_logger(__name__)

DEFAULT_UTILITY_WORKER_COUNT = int(DEFAULT_SYSTEM_CONFIG["utility_worker_count"][0])
DEFAULT_UTILITY_LOG_LEVEL = str(DEFAULT_SYSTEM_CONFIG["utility_log_level"][0]).upper()


async def get_utility_worker_count(session: Any) -> int:
    """Load the configured per-job worker count, falling back to the default."""
    result = await session.execute(
        select(SystemConfig.value).where(SystemConfig.key == "utility_worker_count").limit(1)
    )
    raw_value = result.scalar_one_or_none()
    if raw_value is None:
        return DEFAULT_UTILITY_WORKER_COUNT

    try:
        parsed_value = int(raw_value)
    except (TypeError, ValueError):
        logger.warning(
            "invalid_utility_worker_count",
            value=raw_value,
            fallback=DEFAULT_UTILITY_WORKER_COUNT,
        )
        return DEFAULT_UTILITY_WORKER_COUNT

    if parsed_value < 1:
        logger.warning(
            "invalid_utility_worker_count",
            value=raw_value,
            fallback=DEFAULT_UTILITY_WORKER_COUNT,
        )
        return DEFAULT_UTILITY_WORKER_COUNT

    return parsed_value


async def get_utility_log_level(session: Any) -> str:
    """Load the configured utility log threshold, falling back to the default."""
    result = await session.execute(
        select(SystemConfig.value).where(SystemConfig.key == "utility_log_level").limit(1)
    )
    raw_value = result.scalar_one_or_none()
    if raw_value is None:
        return DEFAULT_UTILITY_LOG_LEVEL

    normalized = str(raw_value).upper()
    if normalized not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
        logger.warning(
            "invalid_utility_log_level",
            value=raw_value,
            fallback=DEFAULT_UTILITY_LOG_LEVEL,
        )
        return DEFAULT_UTILITY_LOG_LEVEL
    return normalized
