"""Download stall recovery module characterization tests."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_stall_timeout_uses_shared_config_resolver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The extracted stall-recovery module should own stall timeout config loading."""
    from pullbox.tasks import download_stall_recovery

    calls: list[tuple[str, ...]] = []

    async def fake_load_system_config_values(
        session: AsyncMock,
        keys: tuple[str, ...],
    ) -> dict[str, str]:
        _ = session
        calls.append(keys)
        return {"stall_timeout_hours": "2"}

    monkeypatch.setattr(
        download_stall_recovery,
        "load_system_config_values",
        fake_load_system_config_values,
    )

    timeout = await download_stall_recovery._get_stall_timeout(AsyncMock())

    assert timeout == timedelta(hours=2)
    assert calls == [("stall_timeout_hours",)]
