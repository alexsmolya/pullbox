"""Task-level search config resolver coverage."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_mocked_two_pass_toggle_uses_shared_config_resolver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The mocked search path should use the shared config resolver."""
    from pullbox.tasks import search_task

    calls: list[tuple[str, ...]] = []

    async def fake_load_system_config_values(
        session: AsyncMock,
        keys: tuple[str, ...],
    ) -> dict[str, str]:
        _ = session
        calls.append(keys)
        return {"search_two_pass_enabled": "false"}

    monkeypatch.setattr(
        search_task,
        "load_system_config_values",
        fake_load_system_config_values,
        raising=False,
    )

    enabled = await search_task._load_mocked_two_pass_enabled(
        AsyncMock(),
        SimpleNamespace(two_pass_enabled=True),
    )

    assert enabled is False
    assert calls == [("search_two_pass_enabled",)]


@pytest.mark.asyncio
async def test_search_log_retention_uses_shared_config_resolver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Search log retention should use the shared config resolver."""
    from pullbox.tasks import search_task

    calls: list[tuple[str, ...]] = []

    async def fake_load_system_config_values(
        session: AsyncMock,
        keys: tuple[str, ...],
    ) -> dict[str, str]:
        _ = session
        calls.append(keys)
        return {"search_log_retention_days": "30"}

    monkeypatch.setattr(
        search_task,
        "load_system_config_values",
        fake_load_system_config_values,
        raising=False,
    )

    retention_days = await search_task._load_search_log_retention_days(AsyncMock())

    assert retention_days == 30
    assert calls == [("search_log_retention_days",)]
