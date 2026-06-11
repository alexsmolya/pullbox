"""Tests for library root resolution helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from pullbox.core.exceptions import ConfigurationError
from pullbox.core.library_root_resolution import (
    materialize_series_path,
    path_is_inside_root,
    resolve_library_root,
    resolve_path_inside_roots,
)
from pullbox.models.config import SystemConfig
from pullbox.models.library import LibraryRoot
from pullbox.models.series import Series


@pytest.mark.asyncio
async def test_resolve_library_root_prefers_explicit_root(db_session, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    first_path = tmp_path / "first"
    second_path = tmp_path / "second"
    first_path.mkdir()
    second_path.mkdir()
    first = LibraryRoot(name="First", path=str(first_path), enabled=True)
    second = LibraryRoot(name="Second", path=str(second_path), enabled=True)
    db_session.add_all([first, second])
    await db_session.flush()

    root = await resolve_library_root(
        db_session,
        second_path / "download.cbz",
        first.id,
    )

    assert root.id == first.id


@pytest.mark.asyncio
async def test_resolve_library_root_uses_series_path_when_available(
    db_session,
    tmp_path: Path,
) -> None:  # type: ignore[no-untyped-def]
    root_path = tmp_path / "comics"
    series_path = root_path / "Batman (2026)"
    series_path.mkdir(parents=True)
    root = LibraryRoot(name="Comics", path=str(root_path), enabled=True)
    series = Series(title="Batman", sort_title="batman", path=str(series_path))
    db_session.add_all([root, series])
    await db_session.flush()

    resolved = await resolve_library_root(
        db_session,
        tmp_path / "imports" / "Batman 001.cbz",
        None,
        series=series,
    )

    assert resolved.id == root.id


@pytest.mark.asyncio
async def test_resolve_library_root_falls_back_to_comics_directory_config(
    db_session,
    tmp_path: Path,
) -> None:  # type: ignore[no-untyped-def]
    root_path = tmp_path / "configured"
    root_path.mkdir()
    root = LibraryRoot(name="Configured", path=str(root_path), enabled=True)
    db_session.add(root)
    db_session.add(SystemConfig(key="comics_directory", value=str(root_path), value_type="string"))
    await db_session.flush()

    resolved = await resolve_library_root(
        db_session,
        tmp_path / "outside" / "file.cbz",
        None,
    )

    assert resolved.id == root.id


@pytest.mark.asyncio
async def test_resolve_library_root_raises_without_any_configured_root(db_session) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ConfigurationError, match="No comics directory configured"):
        await resolve_library_root(db_session, Path("/imports/file.cbz"), None)


def test_path_is_inside_root_and_materialize_series_path(tmp_path: Path) -> None:
    root = LibraryRoot(name="Comics", path=str(tmp_path), enabled=True, id=10)
    series_path = tmp_path / "Series"
    series = Series(title="Series", sort_title="series")

    assert path_is_inside_root(series_path / "issue.cbz", root) is True
    assert path_is_inside_root(tmp_path.parent / "other" / "issue.cbz", root) is False

    materialize_series_path(series, series_path, root)

    assert series.path == str(series_path)
    assert series.library_root_id == root.id


def test_resolve_path_inside_roots_returns_resolved_child(tmp_path: Path) -> None:
    root = tmp_path / "library"
    nested = root / "Series"
    nested.mkdir(parents=True)

    resolved = resolve_path_inside_roots(nested / ".." / "Series", [root], require_dir=True)

    assert resolved == nested.resolve()


def test_resolve_path_inside_roots_rejects_prefix_sibling(tmp_path: Path) -> None:
    root = tmp_path / "library"
    sibling = tmp_path / "library-other"
    root.mkdir()
    sibling.mkdir()

    with pytest.raises(ValueError, match="outside"):
        resolve_path_inside_roots(sibling, [root], require_dir=True)


def test_resolve_path_inside_roots_rejects_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "library"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    escape = root / "escape"
    escape.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="outside"):
        resolve_path_inside_roots(escape, [root], require_dir=True)


def test_resolve_path_inside_roots_enforces_file_requirement(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()

    with pytest.raises(ValueError, match="file"):
        resolve_path_inside_roots(root, [root], require_file=True)
