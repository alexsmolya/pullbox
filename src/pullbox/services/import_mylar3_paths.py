"""Mylar3 path mapping helpers for collection import."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Protocol

import structlog


class DebugLogger(Protocol):
    """Small logging protocol used to preserve import-service log routing."""

    def debug(self, event: str, **kwargs: object) -> object: ...


logger = structlog.get_logger(__name__)


def auto_detect_mylar3_path_map(
    db_path: Path,
    *,
    log: DebugLogger = logger,
) -> dict[str, str] | None:
    """Auto-detect path mapping for Mylar3 by examining ComicLocation values."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        rows = conn.execute(
            "SELECT ComicLocation FROM comics "
            "WHERE ComicLocation IS NOT NULL AND ComicLocation != '' "
            "LIMIT 50"
        ).fetchall()
        conn.close()
    except sqlite3.DatabaseError:
        return None

    if not rows:
        return None

    for row in rows:
        comic_location: str = row[0]
        detected = _detect_path_map_for_location(db_path, comic_location)
        if detected is None:
            continue
        container_prefix, host_path = detected
        path_map = {container_prefix: host_path}
        log.debug(
            "mylar3_path_map_auto_detected",
            container_prefix=container_prefix,
            host_path=host_path,
            comic_location=comic_location,
        )
        return path_map

    return None


def _detect_path_map_for_location(
    db_path: Path,
    comic_location: str,
) -> tuple[str, str] | None:
    """Return a validated path map for one Mylar ComicLocation."""
    location_path = Path(comic_location)
    if not location_path.is_absolute():
        return None

    for container_prefix in _container_prefixes(location_path):
        search_name = Path(container_prefix).name
        relative_location = location_path.relative_to(container_prefix)
        for search_dir in _path_map_search_dirs(db_path):
            candidate_root = search_dir / search_name
            if not candidate_root.is_dir():
                continue
            if _same_path(candidate_root, Path(container_prefix)):
                continue
            translated_location = candidate_root / relative_location
            if not translated_location.is_dir():
                continue
            return container_prefix, str(candidate_root)
    return None


def _container_prefixes(location_path: Path) -> list[str]:
    """Return possible Mylar container prefixes, deepest useful prefix first."""
    parts = location_path.parts
    if len(parts) < 3 or parts[0] != "/":
        return []

    segments = parts[1:]
    return [str(Path("/", *segments[:index])) for index in range(len(segments) - 1, 0, -1)]


def _path_map_search_dirs(db_path: Path) -> list[Path]:
    """Return nearby directories to probe for host-side mount names."""
    search_dirs = [
        db_path.parent,
        db_path.parent.parent,
        db_path.parent.parent.parent,
    ]
    unique_dirs: list[Path] = []
    for search_dir in search_dirs:
        if search_dir not in unique_dirs:
            unique_dirs.append(search_dir)
    return unique_dirs


def _same_path(left: Path, right: Path) -> bool:
    """Return whether two paths refer to the same path without requiring existence."""
    return left.resolve(strict=False) == right.resolve(strict=False)
