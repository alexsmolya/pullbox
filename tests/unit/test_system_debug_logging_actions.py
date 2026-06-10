"""Direct tests for system debug-logging API helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from pullbox.api.v1.system_debug_logging import (
    DebugLoggingRequest,
    disable_debug_logging_response,
    enable_debug_logging_response,
    get_debug_logging_status_response,
)
from pullbox.models.config import SystemConfig

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_enable_debug_logging_response_preserves_base_level(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Enabling debug logging should store override keys and apply debug at runtime."""
    db_session.add(SystemConfig(key="log_level", value="warning", value_type="string"))
    await db_session.commit()
    reconfigured: list[str] = []
    monkeypatch.setattr(
        "pullbox.logging.reconfigure_logging_runtime",
        lambda *, log_level: reconfigured.append(log_level),
    )

    response = await enable_debug_logging_response(
        DebugLoggingRequest(duration_minutes=30, level="verbose"),
        db_session,
    )

    assert response.active is True
    assert response.level == "debug"
    assert response.base_level == "warning"
    assert response.remaining_minutes == 30
    assert reconfigured == ["debug"]

    result = await db_session.execute(
        select(SystemConfig).where(
            SystemConfig.key.in_(
                ("log_level_override", "log_level_override_expires", "log_level_base")
            )
        )
    )
    cfg = {row.key: row.value for row in result.scalars().all()}
    assert cfg["log_level_override"] == "debug"
    assert cfg["log_level_base"] == "warning"
    assert datetime.fromisoformat(cfg["log_level_override_expires"]) > datetime.now(UTC)


@pytest.mark.asyncio
async def test_get_debug_logging_status_response_reports_active_override(
    db_session: AsyncSession,
) -> None:
    """Status should include active override level, base level, expiry, and remaining time."""
    expires_at = datetime.now(UTC) + timedelta(minutes=45)
    db_session.add_all(
        [
            SystemConfig(key="log_level", value="info", value_type="string"),
            SystemConfig(key="log_level_override", value="debug", value_type="string"),
            SystemConfig(
                key="log_level_override_expires",
                value=expires_at.isoformat(),
                value_type="string",
            ),
            SystemConfig(key="log_level_base", value="warning", value_type="string"),
        ]
    )
    await db_session.commit()

    response = await get_debug_logging_status_response(db_session)

    assert response.active is True
    assert response.level == "debug"
    assert response.base_level == "warning"
    assert response.expires_at == expires_at.isoformat()
    assert response.remaining_minutes is not None
    assert 0 < response.remaining_minutes <= 45


@pytest.mark.asyncio
async def test_disable_debug_logging_response_clears_override_keys(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Disabling debug logging should delete override rows and restore the base level."""
    db_session.add_all(
        [
            SystemConfig(key="log_level", value="info", value_type="string"),
            SystemConfig(key="log_level_override", value="debug", value_type="string"),
            SystemConfig(
                key="log_level_override_expires",
                value=(datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
                value_type="string",
            ),
            SystemConfig(key="log_level_base", value="warning", value_type="string"),
        ]
    )
    await db_session.commit()
    reconfigured: list[str] = []
    monkeypatch.setattr(
        "pullbox.logging.reconfigure_logging_runtime",
        lambda *, log_level: reconfigured.append(log_level),
    )

    response = await disable_debug_logging_response(db_session)

    assert response.active is False
    assert response.base_level == "warning"
    assert reconfigured == ["warning"]
    for key in ("log_level_override", "log_level_override_expires", "log_level_base"):
        assert await db_session.get(SystemConfig, key) is None
