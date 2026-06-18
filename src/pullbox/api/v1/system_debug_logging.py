"""Temporary debug-logging API schemas and action helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from pydantic import BaseModel, Field
from sqlalchemy import delete as sa_delete
from sqlalchemy import select

from pullbox import logging as logging_runtime
from pullbox.models.config import SystemConfig
from pullbox.services.debug_logging_service import expire_debug_logging_override_if_needed

logger = structlog.get_logger(__name__)


class DebugLoggingRequest(BaseModel):
    """Request to enable temporary debug logging."""

    duration_minutes: int = Field(
        15, ge=15, le=1440, description="Duration in minutes (15min to 24hr)"
    )
    level: str = Field("debug", pattern="^(debug|verbose)$")


class DebugLoggingStatusResponse(BaseModel):
    """Current debug logging override status."""

    active: bool
    level: str | None = None
    base_level: str | None = None
    expires_at: str | None = None
    remaining_minutes: int | None = None


async def check_and_clear_expired_debug_logging_override(session: Any) -> bool:
    """Check if a debug logging override has expired and clear it if so."""
    return await expire_debug_logging_override_if_needed(session, source="status")


async def get_debug_logging_status_response(session: Any) -> DebugLoggingStatusResponse:
    """Return current debug logging override status."""
    await check_and_clear_expired_debug_logging_override(session)

    result = await session.execute(
        select(SystemConfig).where(
            SystemConfig.key.in_(
                (
                    "log_level_override",
                    "log_level_override_expires",
                    "log_level_base",
                    "log_level",
                )
            )
        )
    )
    cfg = {row.key: row.value for row in result.scalars().all()}

    if "log_level_override" not in cfg:
        return DebugLoggingStatusResponse(
            active=False,
            base_level=cfg.get("log_level", "info"),
        )

    expires_str = cfg.get("log_level_override_expires")
    remaining: int | None = None
    if expires_str:
        expires_at = datetime.fromisoformat(expires_str)
        delta = (expires_at - datetime.now(UTC)).total_seconds()
        remaining = max(0, int(delta / 60))

    return DebugLoggingStatusResponse(
        active=True,
        level=cfg["log_level_override"],
        base_level=cfg.get("log_level_base", cfg.get("log_level", "info")),
        expires_at=expires_str,
        remaining_minutes=remaining,
    )


async def enable_debug_logging_response(
    body: DebugLoggingRequest,
    session: Any,
) -> DebugLoggingStatusResponse:
    """Enable temporary debug logging with auto-expiry."""
    result = await session.execute(
        select(SystemConfig).where(
            SystemConfig.key.in_(
                (
                    "log_level",
                    "log_level_base",
                    "log_level_override",
                    "log_level_override_expires",
                )
            )
        )
    )
    cfg = {row.key: row for row in result.scalars().all()}

    if "log_level_base" in cfg:
        base_level = cfg["log_level_base"].value
    elif "log_level" in cfg:
        base_level = cfg["log_level"].value
    else:
        base_level = "info"

    override_level = body.level if body.level != "verbose" else "debug"
    expires_at = datetime.now(UTC) + timedelta(minutes=body.duration_minutes)

    override_keys = {
        "log_level_override": (override_level, "string"),
        "log_level_override_expires": (expires_at.isoformat(), "string"),
        "log_level_base": (base_level, "string"),
    }
    for key, (value, value_type) in override_keys.items():
        if key in cfg:
            cfg[key].value = value
        else:
            session.add(SystemConfig(key=key, value=value, value_type=value_type))
    await session.commit()

    logging_runtime.reconfigure_logging_runtime(log_level=override_level)

    remaining = max(0, int(body.duration_minutes))
    logger.info(
        "debug_logging_enabled",
        level=override_level,
        duration_minutes=body.duration_minutes,
        expires_at=expires_at.isoformat(),
        base_level=base_level,
    )

    return DebugLoggingStatusResponse(
        active=True,
        level=override_level,
        base_level=base_level,
        expires_at=expires_at.isoformat(),
        remaining_minutes=remaining,
    )


async def disable_debug_logging_response(session: Any) -> DebugLoggingStatusResponse:
    """Disable debug logging override and revert to normal level."""
    result = await session.execute(
        select(SystemConfig).where(SystemConfig.key.in_(("log_level_base", "log_level")))
    )
    cfg = {row.key: row.value for row in result.scalars().all()}
    base_level = cfg.get("log_level_base", cfg.get("log_level", "info"))

    await session.execute(
        sa_delete(SystemConfig).where(
            SystemConfig.key.in_(
                ("log_level_override", "log_level_override_expires", "log_level_base")
            )
        )
    )
    await session.commit()

    logging_runtime.reconfigure_logging_runtime(log_level=base_level)

    logger.info("debug_logging_disabled", reverted_to=base_level)

    return DebugLoggingStatusResponse(
        active=False,
        base_level=base_level,
    )
