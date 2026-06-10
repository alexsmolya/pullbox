"""Unit tests for utility logging runtime configuration hooks."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from pullbox.app import _apply_db_utility_logging_overrides
from pullbox.config import get_settings
from pullbox.models.config import SystemConfig

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
async def test_apply_db_utility_logging_overrides_uses_db_level_and_runtime_logs_dir(
    async_engine,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:  # type: ignore[no-untyped-def]
    factory = async_sessionmaker(async_engine, expire_on_commit=False)

    async with factory() as session:
        session.add(SystemConfig(key="utility_log_level", value="DEBUG", value_type="string"))
        await session.commit()

    calls: list[tuple[Path, str]] = []

    def _fake_reconfigure(log_dir: Path, level: str = "INFO") -> None:
        calls.append((log_dir, level))

    monkeypatch.setattr("pullbox.app.get_session_factory", lambda: factory)
    monkeypatch.setattr(
        "pullbox.utilities.logging_config.configure_utility_logging_runtime",
        _fake_reconfigure,
    )
    monkeypatch.setenv("PULLBOX_LOGS_DIR", str(tmp_path))
    get_settings.cache_clear()
    try:
        await _apply_db_utility_logging_overrides(get_settings())
    finally:
        get_settings.cache_clear()

    assert calls == [(tmp_path, "DEBUG")]
