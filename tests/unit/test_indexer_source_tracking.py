"""Unit tests for indexer source tracking validation (DCE-S.4).

Verifies that IndexerSource enum values and the source column on
IndexerConfig work correctly for both manual and Prowlarr-synced indexers.

Run:
    pytest tests/unit/test_indexer_source_tracking.py -v
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from pullbox.models import Base
from pullbox.models.indexer import IndexerConfig, IndexerSource, IndexerType

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-indexer-source")


@pytest.fixture
async def db() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    """Create an in-memory database with all tables."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
async def session(db: async_sessionmaker[AsyncSession]) -> AsyncGenerator[AsyncSession, None]:
    """Provide a single session for each test."""
    async with db() as sess:
        yield sess


class TestIndexerSourceEnum:
    """Tests for IndexerSource enum values."""

    def test_manual_value(self) -> None:
        assert IndexerSource.MANUAL == "manual"

    def test_prowlarr_value(self) -> None:
        assert IndexerSource.PROWLARR == "prowlarr"

    def test_jackett_value(self) -> None:
        assert IndexerSource.JACKETT == "jackett"

    def test_exactly_three_members(self) -> None:
        assert len(list(IndexerSource)) == 3


@pytest.mark.asyncio
class TestManualIndexerSource:
    """Manual indexer creation sets source='manual'."""

    async def test_manual_indexer_defaults_to_manual(self, session: AsyncSession) -> None:
        config = IndexerConfig(
            name="NZBgeek",
            indexer_type=IndexerType.NEWZNAB,
            url="https://api.nzbgeek.info/",
            api_key="test-key",
        )
        session.add(config)
        await session.flush()
        await session.refresh(config)

        assert config.source == "manual"

    async def test_explicit_manual_source(self, session: AsyncSession) -> None:
        config = IndexerConfig(
            name="NZBgeek",
            indexer_type=IndexerType.NEWZNAB,
            url="https://api.nzbgeek.info/",
            api_key="test-key",
            source="manual",
        )
        session.add(config)
        await session.flush()
        await session.refresh(config)

        assert config.source == "manual"


@pytest.mark.asyncio
class TestProwlarrIndexerSource:
    """Prowlarr-synced indexers have source='prowlarr'."""

    async def test_prowlarr_source_persists(self, session: AsyncSession) -> None:
        config = IndexerConfig(
            name="1337x (Prowlarr)",
            indexer_type=IndexerType.TORZNAB,
            url="http://prowlarr:9696/1/api",
            api_key="prowlarr-key",
            source="prowlarr",
            prowlarr_indexer_id=1,
        )
        session.add(config)
        await session.flush()
        await session.refresh(config)

        assert config.source == "prowlarr"
        assert config.prowlarr_indexer_id == 1


@pytest.mark.asyncio
class TestManagedIndexerState:
    """Manager identity and availability remain independent of local settings."""

    async def test_jackett_manager_fields_persist(self, session: AsyncSession) -> None:
        config = IndexerConfig(
            name="1337x (Jackett)",
            indexer_type=IndexerType.TORZNAB,
            url="http://jackett:9117/api/v2.0/indexers/1337x/results/torznab",
            api_key="jackett-key",
            source="jackett",
            manager_indexer_id="1337x",
            manager_available=False,
        )
        session.add(config)
        await session.flush()
        await session.refresh(config)

        assert config.source == "jackett"
        assert config.manager_indexer_id == "1337x"
        assert config.manager_available is False

    async def test_manual_indexer_defaults_to_available(self, session: AsyncSession) -> None:
        config = IndexerConfig(
            name="Manual",
            indexer_type=IndexerType.TORZNAB,
            url="http://indexer.example",
            api_key="key",
        )
        session.add(config)
        await session.flush()
        await session.refresh(config)

        assert config.manager_available is True


@pytest.mark.asyncio
class TestFilterBySource:
    """Indexers can be filtered by source."""

    async def test_filter_manual_only(self, session: AsyncSession) -> None:
        manual = IndexerConfig(
            name="Manual NZB",
            indexer_type=IndexerType.NEWZNAB,
            url="http://a.com",
            api_key="k1",
            source="manual",
        )
        prowlarr = IndexerConfig(
            name="Prowlarr Torznab",
            indexer_type=IndexerType.TORZNAB,
            url="http://b.com",
            api_key="k2",
            source="prowlarr",
        )
        session.add_all([manual, prowlarr])
        await session.flush()

        result = await session.execute(
            select(IndexerConfig).where(IndexerConfig.source == "manual")
        )
        configs = list(result.scalars().all())
        assert len(configs) == 1
        assert configs[0].name == "Manual NZB"

    async def test_filter_prowlarr_only(self, session: AsyncSession) -> None:
        manual = IndexerConfig(
            name="Manual",
            indexer_type=IndexerType.NEWZNAB,
            url="http://a.com",
            api_key="k1",
            source="manual",
        )
        prowlarr = IndexerConfig(
            name="Prowlarr",
            indexer_type=IndexerType.TORZNAB,
            url="http://b.com",
            api_key="k2",
            source="prowlarr",
        )
        session.add_all([manual, prowlarr])
        await session.flush()

        result = await session.execute(
            select(IndexerConfig).where(IndexerConfig.source == "prowlarr")
        )
        configs = list(result.scalars().all())
        assert len(configs) == 1
        assert configs[0].name == "Prowlarr"
