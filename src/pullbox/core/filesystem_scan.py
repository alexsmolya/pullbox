"""Helpers for deterministic recursive filesystem scans."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

logger = structlog.get_logger(__name__)


def _default_onerror(root: Path, exc: OSError) -> None:
    logger.warning(
        "filesystem_scan_walk_error",
        root=str(root),
        path=getattr(exc, "filename", None),
        error=str(exc),
    )


def iter_supported_files(root: Path, allowed_extensions: frozenset[str]) -> Iterator[Path]:
    """Yield supported files recursively in deterministic order.

    Unreadable directories are skipped with a warning so a single bad subtree
    does not abort an entire user-initiated scan.
    """
    if not root.exists() or not root.is_dir():
        return

    def _onerror(exc: OSError) -> None:
        _default_onerror(root, exc)

    for current_root, dir_names, file_names in os.walk(root, onerror=_onerror):
        dir_names.sort()
        file_names.sort()
        current_root_path = Path(current_root)
        for file_name in file_names:
            file_path = current_root_path / file_name
            if file_path.suffix.lower() in allowed_extensions:
                yield file_path


def iter_supported_files_with_handler(
    root: Path,
    allowed_extensions: frozenset[str],
    on_error: Callable[[Path, OSError], None],
) -> Iterator[Path]:
    """Yield supported files recursively using a caller-provided error handler."""
    if not root.exists() or not root.is_dir():
        return

    def _onerror(exc: OSError) -> None:
        on_error(root, exc)

    for current_root, dir_names, file_names in os.walk(root, onerror=_onerror):
        dir_names.sort()
        file_names.sort()
        current_root_path = Path(current_root)
        for file_name in file_names:
            file_path = current_root_path / file_name
            if file_path.suffix.lower() in allowed_extensions:
                yield file_path
