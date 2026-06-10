"""Unit tests for Series model fields.

Run:
    pytest tests/unit/test_series_model.py -v
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from pullbox.models import Base
from pullbox.models.series import IssueCatalogState, Series

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-series-tests")


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


@pytest.mark.asyncio
class TestMonitored:
    """Tests for the monitored field on Series."""

    async def test_monitored_defaults_false(self, session: AsyncSession) -> None:
        """Creating a Series without setting monitored defaults to False."""
        series = Series(
            title="Batman",
            sort_title="batman",
        )
        session.add(series)
        await session.flush()
        await session.refresh(series)

        assert series.monitored is False

    async def test_monitored_set_true(self, session: AsyncSession) -> None:
        """Creating a Series with monitored=True persists correctly."""
        series = Series(
            title="Spider-Man",
            sort_title="spider-man",
            monitored=True,
        )
        session.add(series)
        await session.flush()
        await session.refresh(series)

        assert series.monitored is True


@pytest.mark.asyncio
class TestIssueCatalogState:
    """Tests for partial/full ComicVine issue catalog tracking."""

    async def test_catalog_state_defaults_complete(self, session: AsyncSession) -> None:
        series = Series(
            title="Batman",
            sort_title="batman",
        )
        session.add(series)
        await session.flush()
        await session.refresh(series)

        assert series.issue_catalog_state == IssueCatalogState.COMPLETE
        assert series.issue_catalog_last_synced_at is None
        assert series.issue_catalog_last_checked_at is None
        assert series.issue_catalog_error is None

    async def test_catalog_state_can_be_marked_hydrating(self, session: AsyncSession) -> None:
        series = Series(
            title="2000AD",
            sort_title="2000ad",
            issue_catalog_state=IssueCatalogState.HYDRATING,
        )
        session.add(series)
        await session.flush()
        await session.refresh(series)

        assert series.issue_catalog_state == IssueCatalogState.HYDRATING
