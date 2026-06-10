"""Tests for background backfill of existing series covers."""

from __future__ import annotations

import contextlib
import os
import sys
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from pullbox.models import Base
from pullbox.models.series import Series, SeriesStatus, SeriesType

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator
    from pathlib import Path

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-cover-backfill")

_MOD = "pullbox.tasks.cover_backfill_task"


@pytest.fixture
async def db_factory() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _create_series(
    factory: async_sessionmaker[AsyncSession],
    *,
    title: str,
    cover_url: str | None = None,
    cover_path: str | None = None,
) -> int:
    async with factory() as session:
        series = Series(
            title=title,
            sort_title=title,
            year_start=2024,
            status=SeriesStatus.CONTINUING,
            series_type=SeriesType.STANDARD,
            monitored=True,
            cover_url=cover_url,
            cover_path=cover_path,
        )
        session.add(series)
        await session.commit()
        return series.id


@contextlib.contextmanager
def _task_patches(
    db_factory: async_sessionmaker[AsyncSession],
    *,
    resolve_cover: AsyncMock,
    cache_cover: AsyncMock,
) -> Generator[None, None, None]:
    with (
        patch(f"{_MOD}.get_session_factory", return_value=db_factory),
        patch(f"{_MOD}.resolve_series_cover_file", resolve_cover),
        patch(f"{_MOD}.cache_series_cover", cache_cover),
    ):
        yield


@pytest.mark.asyncio
async def test_backfill_links_existing_local_cover_without_redownload(
    db_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    series_id = await _create_series(
        db_factory,
        title="Batman",
        cover_url="https://example.test/batman.jpg",
        cover_path=None,
    )
    existing_cover = tmp_path / "series.jpg"
    existing_cover.write_bytes(b"cover")

    resolve_cover = AsyncMock(return_value=existing_cover)
    cache_cover = AsyncMock(return_value=None)

    with _task_patches(
        db_factory,
        resolve_cover=resolve_cover,
        cache_cover=cache_cover,
    ):
        from pullbox.tasks.cover_backfill_task import backfill_series_covers

        stats = await backfill_series_covers()

    async with db_factory() as session:
        series = await session.get(Series, series_id)
        assert series is not None
        assert series.cover_path == f"/api/v1/series/{series_id}/cover"

    assert stats.processed == 1
    assert stats.linked_existing == 1
    assert stats.downloaded == 0
    cache_cover.assert_not_awaited()


@pytest.mark.asyncio
async def test_backfill_downloads_and_links_remote_cover_when_missing(
    db_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    series_id = await _create_series(
        db_factory,
        title="Saga",
        cover_url="https://example.test/saga.jpg",
        cover_path=None,
    )

    resolve_cover = AsyncMock(return_value=None)

    async def _cache_cover(session: AsyncSession, series: Series) -> Path:
        series.cover_path = f"/api/v1/series/{series.id}/cover"
        return tmp_path / "cached-series.jpg"

    cache_cover = AsyncMock(side_effect=_cache_cover)

    with _task_patches(
        db_factory,
        resolve_cover=resolve_cover,
        cache_cover=cache_cover,
    ):
        from pullbox.tasks.cover_backfill_task import backfill_series_covers

        stats = await backfill_series_covers()

    async with db_factory() as session:
        series = await session.get(Series, series_id)
        assert series is not None
        assert series.cover_path == f"/api/v1/series/{series_id}/cover"

    assert stats.processed == 1
    assert stats.downloaded == 1
    assert stats.linked_existing == 0
    cache_cover.assert_awaited_once()


@pytest.mark.asyncio
async def test_backfill_respects_limit_and_prioritizes_missing_links(
    db_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    first_id = await _create_series(
        db_factory,
        title="Alpha",
        cover_url="https://example.test/alpha.jpg",
        cover_path=None,
    )
    second_id = await _create_series(
        db_factory,
        title="Beta",
        cover_url="https://example.test/beta.jpg",
        cover_path=None,
    )

    async def _resolve_cover(session: AsyncSession, series: Series) -> Path | None:
        del session
        del series
        return None

    async def _cache_cover(session: AsyncSession, series: Series) -> Path:
        series.cover_path = f"/api/v1/series/{series.id}/cover"
        return tmp_path / f"{series.id}.jpg"

    with _task_patches(
        db_factory,
        resolve_cover=AsyncMock(side_effect=_resolve_cover),
        cache_cover=AsyncMock(side_effect=_cache_cover),
    ):
        from pullbox.tasks.cover_backfill_task import backfill_series_covers

        stats = await backfill_series_covers(limit=1)

    async with db_factory() as session:
        first = await session.get(Series, first_id)
        second = await session.get(Series, second_id)
        assert first is not None
        assert second is not None
        updated = {
            sid
            for sid, cover in ((first.id, first.cover_path), (second.id, second.cover_path))
            if cover
        }

    assert stats.processed == 1
    assert stats.downloaded == 1
    assert len(updated) == 1
