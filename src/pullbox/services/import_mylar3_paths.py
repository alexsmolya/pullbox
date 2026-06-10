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
        row = conn.execute(
            "SELECT ComicLocation FROM comics WHERE ComicLocation IS NOT NULL LIMIT 1"
        ).fetchone()
        conn.close()
    except sqlite3.DatabaseError:
        return None

    if not row or not row[0]:
        return None

    comic_location: str = row[0]
    parts = Path(comic_location).parts
    if len(parts) < 2:
        return None
    container_prefix = str(Path(*parts[:2]))

    search_name = parts[1]
    search_dirs = [
        db_path.parent,
        db_path.parent.parent,
        db_path.parent.parent.parent,
    ]
    for search_dir in search_dirs:
        candidate = search_dir / search_name
        if candidate.is_dir():
            path_map = {container_prefix: str(candidate)}
            log.debug(
                "mylar3_path_map_auto_detected",
                container_prefix=container_prefix,
                host_path=str(candidate),
            )
            return path_map

    return None
