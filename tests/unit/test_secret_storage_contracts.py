"""Secret-at-rest storage contracts for sensitive configuration writes."""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from pullbox.api.v1.indexers import sync_jackett_indexers, sync_prowlarr_indexers
from pullbox.core.encryption import decrypt_secret, is_encrypted
from pullbox.models import Base
from pullbox.models.config import SystemConfig
from pullbox.models.indexer import IndexerConfig
from pullbox.schemas.indexer import JackettSyncRequest, ProwlarrSyncRequest

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-secret-storage")


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db_session:
        yield db_session
    await engine.dispose()


class _FakeProwlarrIndexer:
    def __init__(self, *, url: str, api_key: str) -> None:
        self.url = url
        self.api_key = api_key

    async def get_indexers(self) -> list[dict[str, Any]]:
        return [
            {
                "id": 7,
                "name": "MAM",
                "protocol": "torrent",
                "priority": 25,
                "enable": True,
                "capabilities": {"categories": [{"id": 7030}]},
            }
        ]

    async def close(self) -> None:
        return None


class _FakeJackettClient:
    def __init__(self, *, url: str, api_key: str) -> None:
        self.url = url
        self.api_key = api_key

    async def get_configured_indexers(self) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(
                id="1337x",
                name="1337x",
                description="Public tracker",
                categories=("7030",),
                search_modes=("search",),
            )
        ]

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_prowlarr_sync_stores_system_api_key_as_encrypted_secret(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "pullbox.providers.indexer.prowlarr.ProwlarrIndexer",
        _FakeProwlarrIndexer,
    )

    await sync_prowlarr_indexers(
        ProwlarrSyncRequest(
            prowlarr_url="http://prowlarr:9696",
            prowlarr_api_key="prowlarr-secret",
        ),
        None,  # type: ignore[arg-type]
        session,
    )

    prowlarr_key = await session.get(SystemConfig, "prowlarr_api_key")
    assert prowlarr_key is not None
    assert prowlarr_key.value_type == "secret"
    assert is_encrypted(prowlarr_key.value)
    assert decrypt_secret(prowlarr_key.value) == "prowlarr-secret"

    result = await session.execute(select(IndexerConfig))
    indexer = result.scalar_one()
    assert is_encrypted(indexer.api_key)
    assert decrypt_secret(indexer.api_key) == "prowlarr-secret"


@pytest.mark.asyncio
async def test_prowlarr_sync_upgrades_existing_system_api_key_to_secret_type(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "pullbox.providers.indexer.prowlarr.ProwlarrIndexer",
        _FakeProwlarrIndexer,
    )
    session.add(SystemConfig(key="prowlarr_api_key", value="legacy-plain", value_type="string"))
    await session.flush()

    await sync_prowlarr_indexers(
        ProwlarrSyncRequest(
            prowlarr_url="http://prowlarr:9696",
            prowlarr_api_key="rotated-prowlarr-secret",
        ),
        None,  # type: ignore[arg-type]
        session,
    )

    prowlarr_key = await session.get(SystemConfig, "prowlarr_api_key")
    assert prowlarr_key is not None
    assert prowlarr_key.value_type == "secret"
    assert is_encrypted(prowlarr_key.value)
    assert decrypt_secret(prowlarr_key.value) == "rotated-prowlarr-secret"


@pytest.mark.asyncio
async def test_jackett_sync_stores_manager_and_tracker_keys_as_encrypted_secrets(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "pullbox.services.jackett_sync_service.JackettClient",
        _FakeJackettClient,
    )

    await sync_jackett_indexers(
        JackettSyncRequest(
            jackett_url="http://jackett:9117",
            jackett_api_key="jackett-secret",
        ),
        None,  # type: ignore[arg-type]
        session,
    )

    jackett_key = await session.get(SystemConfig, "jackett_api_key")
    assert jackett_key is not None
    assert jackett_key.value_type == "secret"
    assert is_encrypted(jackett_key.value)
    assert decrypt_secret(jackett_key.value) == "jackett-secret"

    result = await session.execute(select(IndexerConfig))
    indexer = result.scalar_one()
    assert is_encrypted(indexer.api_key)
    assert decrypt_secret(indexer.api_key) == "jackett-secret"
