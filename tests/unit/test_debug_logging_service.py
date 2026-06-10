"""Unit tests for temporary debug-logging override helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from pullbox.api.v1.system import DebugLoggingRequest
from pullbox.models import Base
from pullbox.models.config import SystemConfig


@pytest.fixture
async def debug_logging_db():
    """Create an in-memory DB for debug-logging override tests."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


class TestDebugLoggingOverrideHelpers:
    """Shared helper logic should resume and expire overrides correctly."""

    @pytest.mark.asyncio
    async def test_expire_debug_logging_override_if_needed_clears_rows(
        self,
        debug_logging_db,
        monkeypatch,
    ) -> None:
        from pullbox.services.debug_logging_service import expire_debug_logging_override_if_needed

        async with debug_logging_db() as session:
            session.add_all(
                [
                    SystemConfig(key="log_level_override", value="debug", value_type="string"),
                    SystemConfig(
                        key="log_level_override_expires",
                        value=(datetime.now(UTC) - timedelta(minutes=5)).isoformat(),
                        value_type="string",
                    ),
                    SystemConfig(key="log_level_base", value="info", value_type="string"),
                ]
            )
            await session.commit()

        reconfigured: list[str] = []
        monkeypatch.setattr(
            "pullbox.services.debug_logging_service.reconfigure_logging_runtime",
            lambda *, log_level: reconfigured.append(log_level),
        )

        async with debug_logging_db() as session:
            expired = await expire_debug_logging_override_if_needed(session, source="test")

        assert expired is True
        assert reconfigured == ["info"]

        async with debug_logging_db() as session:
            rows = await session.execute(
                select(SystemConfig).where(
                    SystemConfig.key.in_(
                        ("log_level_override", "log_level_override_expires", "log_level_base")
                    )
                )
            )
            assert rows.scalars().all() == []

    @pytest.mark.asyncio
    async def test_restore_debug_logging_override_on_startup_reapplies_active_override(
        self,
        debug_logging_db,
        monkeypatch,
    ) -> None:
        from pullbox.services.debug_logging_service import restore_debug_logging_override_on_startup

        async with debug_logging_db() as session:
            session.add_all(
                [
                    SystemConfig(key="log_level_override", value="debug", value_type="string"),
                    SystemConfig(
                        key="log_level_override_expires",
                        value=(datetime.now(UTC) + timedelta(minutes=15)).isoformat(),
                        value_type="string",
                    ),
                    SystemConfig(key="log_level_base", value="info", value_type="string"),
                ]
            )
            await session.commit()

        reconfigured: list[str] = []
        monkeypatch.setattr(
            "pullbox.services.debug_logging_service.get_session_factory",
            lambda: debug_logging_db,
        )
        monkeypatch.setattr(
            "pullbox.services.debug_logging_service.reconfigure_logging_runtime",
            lambda *, log_level: reconfigured.append(log_level),
        )

        await restore_debug_logging_override_on_startup()

        assert reconfigured == ["debug"]

    def test_debug_logging_request_defaults_to_15_minutes(self) -> None:
        """The support UI/API should default to the shortest supported window."""
        assert DebugLoggingRequest().duration_minutes == 15
