"""Focused tests for search-only registry construction."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from pullbox.composition import providers
from pullbox.providers.base import ProviderRegistry


@pytest.mark.asyncio
async def test_neutral_build_registry_skips_download_clients_when_excluded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    register_indexers = AsyncMock(return_value={1: MagicMock()})
    register_download_clients = AsyncMock()

    monkeypatch.setattr(providers, "register_indexers", register_indexers)
    monkeypatch.setattr(providers, "register_download_clients", register_download_clients)

    result = await providers.build_registry(MagicMock(), include_download_clients=False)

    assert result is not None
    registry, configs = result
    assert isinstance(registry, ProviderRegistry)
    assert configs.keys() == {1}
    register_download_clients.assert_not_awaited()


@pytest.mark.asyncio
async def test_neutral_build_registry_includes_download_clients_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    register_indexers = AsyncMock(return_value={1: MagicMock()})
    register_download_clients = AsyncMock()

    monkeypatch.setattr(providers, "register_indexers", register_indexers)
    monkeypatch.setattr(providers, "register_download_clients", register_download_clients)

    result = await providers.build_registry(MagicMock())

    assert result is not None
    register_download_clients.assert_awaited_once()


def test_production_code_uses_neutral_provider_composition() -> None:
    """Production code should not reintroduce task-owned provider wiring."""
    repo_root = Path(__file__).resolve().parents[2]
    src_root = repo_root / "src" / "pullbox"
    offenders: list[str] = []

    for path in src_root.rglob("*.py"):
        text = path.read_text()
        if "pullbox.tasks._registry" in text or "from pullbox.tasks import _registry" in text:
            offenders.append(path.relative_to(repo_root).as_posix())

    assert offenders == []
