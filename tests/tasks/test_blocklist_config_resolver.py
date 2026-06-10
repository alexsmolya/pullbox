"""Task-level blocklist config resolver coverage."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_cleanup_expired_blocklist_uses_shared_config_resolver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expiry cleanup should resolve config through the shared resolver."""
    from pullbox.tasks import blocklist_task

    calls: list[tuple[str, ...]] = []

    async def fake_load_system_config_values(
        session: AsyncMock,
        keys: tuple[str, ...],
    ) -> dict[str, str]:
        _ = session
        calls.append(keys)
        return {"blocklist.expiry_days": "0"}

    monkeypatch.setattr(
        blocklist_task,
        "load_system_config_values",
        fake_load_system_config_values,
        raising=False,
    )

    session = AsyncMock()
    session.get = AsyncMock(return_value=MagicMock(value="0"))

    removed = await blocklist_task.cleanup_expired_blocklist(session)

    assert removed == 0
    assert calls == [("blocklist.expiry_days",)]


@pytest.mark.asyncio
async def test_auto_blocklist_on_failure_uses_shared_config_resolver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Automatic blocklisting should resolve its toggle through the shared resolver."""
    from pullbox.tasks import download_failure

    calls: list[tuple[str, ...]] = []

    async def fake_load_system_config_values(
        session: AsyncMock,
        keys: tuple[str, ...],
    ) -> dict[str, str]:
        _ = session
        calls.append(keys)
        return {"blocklist.auto_add_on_failure": "false"}

    monkeypatch.setattr(
        download_failure,
        "load_system_config_values",
        fake_load_system_config_values,
        raising=False,
    )

    session = AsyncMock()
    session.get = AsyncMock(return_value=MagicMock(value="false"))
    download = MagicMock(
        id=1,
        title="Batman.001.2026.Digital.Empire",
        download_url="https://example.invalid/release",
        issue_id=100,
        indexer_id=None,
    )

    await download_failure.auto_blocklist_on_download_failure(
        session,
        download,
        "Connection timeout",
    )

    assert calls == [("blocklist.auto_add_on_failure",)]
