"""Tests for resolved library naming and ingest policies."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pullbox.core import library_policy
from pullbox.core.library_policy import load_library_ingest_policy
from pullbox.models.config import DEFAULT_SYSTEM_CONFIG, SystemConfig

if TYPE_CHECKING:
    import pytest
    from sqlalchemy.ext.asyncio import AsyncSession


async def test_library_ingest_policy_defaults_torrent_import_strategy_to_standard(
    db_session: AsyncSession,
) -> None:
    policy = await load_library_ingest_policy(db_session)

    assert policy.torrent_import_strategy == "standard"


async def test_library_ingest_policy_loads_persisted_torrent_import_strategy(
    db_session: AsyncSession,
) -> None:
    db_session.add(
        SystemConfig(
            key="torrent_import_strategy",
            value="seed_safe",
            value_type="string",
        )
    )
    await db_session.flush()

    policy = await load_library_ingest_policy(db_session)

    assert policy.torrent_import_strategy == "seed_safe"


async def test_library_ingest_policy_loads_combined_config_once(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    async def fake_load_system_config_values(
        session: AsyncSession,
        keys: tuple[str, ...],
    ) -> dict[str, str]:
        assert session is db_session
        calls.append(keys)
        return {key: DEFAULT_SYSTEM_CONFIG[key][0] for key in keys}

    monkeypatch.setattr(
        library_policy,
        "load_system_config_values",
        fake_load_system_config_values,
    )

    policy = await load_library_ingest_policy(db_session)

    assert policy.torrent_import_strategy == "standard"
    assert calls == [library_policy._INGEST_KEYS]
