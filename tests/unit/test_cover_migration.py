"""Tests for one-time cover migration into the centralized .covers directory."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pullbox.core.cover_migration import _MIGRATION_KEY, migrate_covers_to_dotcovers
from pullbox.models.config import SystemConfig
from pullbox.models.series import Series, SeriesStatus

if TYPE_CHECKING:
    from pathlib import Path


def _session_factory(async_engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(async_engine, expire_on_commit=False)


def _series(path: Path, comicvine_id: int = 1234) -> Series:
    return Series(
        title=f"Series {comicvine_id}",
        sort_title=f"series {comicvine_id}",
        year_start=2025,
        comicvine_id=comicvine_id,
        status=SeriesStatus.CONTINUING,
        issue_count=0,
        path=str(path),
    )


@pytest.mark.asyncio
async def test_migrate_covers_skips_when_already_marked_complete(
    async_engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _session_factory(async_engine)
    async with factory() as session:
        session.add(SystemConfig(key=_MIGRATION_KEY, value="true"))
        await session.commit()

    async def _unexpected_resolve(*_args: object, **_kwargs: object) -> Path:
        raise AssertionError("completed cover migration should not resolve paths")

    monkeypatch.setattr("pullbox.services.cover_resolver.resolve_covers_dir", _unexpected_resolve)

    assert await migrate_covers_to_dotcovers(factory) == 0


@pytest.mark.asyncio
async def test_migrate_covers_marks_complete_when_no_series_exist(
    async_engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _session_factory(async_engine)

    async def _resolve_covers_dir(_session: AsyncSession) -> Path:
        return tmp_path / ".covers"

    monkeypatch.setattr("pullbox.services.cover_resolver.resolve_covers_dir", _resolve_covers_dir)

    assert await migrate_covers_to_dotcovers(factory) == 0

    async with factory() as session:
        row = await session.get(SystemConfig, _MIGRATION_KEY)
        assert row is not None
        assert row.value == "true"


@pytest.mark.asyncio
async def test_migrate_covers_moves_supported_files_and_skips_existing_destinations(
    async_engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _session_factory(async_engine)
    covers_base = tmp_path / ".covers"
    series_dir = tmp_path / "Series One"
    missing_series_dir = tmp_path / "Missing Series"
    series_dir.mkdir()
    (series_dir / "cover.jpg").write_text("legacy series jpg")
    (series_dir / "cover.png").write_text("legacy series png")
    (series_dir / "issue_001.webp").write_text("issue webp")
    (series_dir / "issue_002.jpg").write_text("existing issue")
    (series_dir / "issue_003.txt").write_text("not an image")
    (series_dir / "other.jpg").write_text("not an issue cover")
    (series_dir / "issue_folder.png").mkdir()
    existing_dest = covers_base / "1" / "series.jpg"
    existing_issue_dest = covers_base / "1" / "issue_002.jpg"
    existing_dest.parent.mkdir(parents=True)
    existing_dest.write_text("already migrated")
    existing_issue_dest.write_text("already migrated issue")

    async def _resolve_covers_dir(_session: AsyncSession) -> Path:
        return covers_base

    monkeypatch.setattr("pullbox.services.cover_resolver.resolve_covers_dir", _resolve_covers_dir)
    async with factory() as session:
        first = _series(series_dir, comicvine_id=111)
        missing = _series(missing_series_dir, comicvine_id=222)
        session.add_all([first, missing])
        await session.flush()
        assert first.id == 1
        await session.commit()

    assert await migrate_covers_to_dotcovers(factory) == 2

    assert (covers_base / "1" / "series.png").read_text() == "legacy series png"
    assert (covers_base / "1" / "issue_001.webp").read_text() == "issue webp"
    assert existing_dest.read_text() == "already migrated"
    assert existing_issue_dest.read_text() == "already migrated issue"
    assert (series_dir / "cover.jpg").exists()
    assert (series_dir / "issue_002.jpg").exists()
    assert (series_dir / "issue_003.txt").exists()
    assert (series_dir / "other.jpg").exists()

    async with factory() as session:
        row = await session.get(SystemConfig, _MIGRATION_KEY)
        assert row is not None
        assert row.value == "true"


@pytest.mark.asyncio
async def test_migrate_covers_marks_complete_when_series_have_no_cover_files(
    async_engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _session_factory(async_engine)
    covers_base = tmp_path / ".covers"
    series_dir = tmp_path / "Empty Series"
    series_dir.mkdir()
    (series_dir / "notes.txt").write_text("not a cover")

    async def _resolve_covers_dir(_session: AsyncSession) -> Path:
        return covers_base

    monkeypatch.setattr("pullbox.services.cover_resolver.resolve_covers_dir", _resolve_covers_dir)
    async with factory() as session:
        session.add(_series(series_dir, comicvine_id=333))
        await session.commit()

    assert await migrate_covers_to_dotcovers(factory) == 0

    async with factory() as session:
        row = await session.get(SystemConfig, _MIGRATION_KEY)
        assert row is not None
        assert row.value == "true"
