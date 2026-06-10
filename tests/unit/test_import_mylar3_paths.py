"""Tests for Mylar3 import path-map helpers."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from pullbox.services.import_mylar3_paths import auto_detect_mylar3_path_map
from pullbox.services.import_service import ImportService

if TYPE_CHECKING:
    from pathlib import Path


def _create_mylar_db(db_path: Path, comic_location: str | None) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE comics (ComicLocation TEXT)")
    if comic_location is not None:
        conn.execute("INSERT INTO comics VALUES (?)", (comic_location,))
    conn.commit()
    conn.close()


def test_auto_detect_mylar3_path_map_matches_nearby_directory(tmp_path: Path) -> None:
    config_dir = tmp_path / "mylar3"
    config_dir.mkdir()
    db_path = config_dir / "mylar.db"
    host_comics = tmp_path / "comics"
    host_comics.mkdir()
    _create_mylar_db(db_path, "/comics/Absolute Wonder Woman (2024)")

    assert auto_detect_mylar3_path_map(db_path) == {"/comics": str(host_comics)}


def test_auto_detect_mylar3_path_map_returns_none_for_empty_comics_table(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "mylar.db"
    _create_mylar_db(db_path, None)

    assert auto_detect_mylar3_path_map(db_path) is None


def test_auto_detect_mylar3_path_map_returns_none_for_invalid_database(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "mylar.db"
    db_path.write_text("not sqlite")

    assert auto_detect_mylar3_path_map(db_path) is None


def test_import_service_mylar3_path_map_shim_remains_available(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "mylar.db"
    _create_mylar_db(db_path, "/comics")

    assert ImportService._auto_detect_mylar3_path_map(db_path) is None
