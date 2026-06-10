"""Source-folder cleanup helpers for download post-processing."""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path


def should_cleanup_source_dir(method: str, download_client: Any) -> bool:
    """Return whether post-processing may remove the source folder."""
    return (
        method == "move"
        and download_client is not None
        and str(download_client).upper() in ("SABNZBD", "NZBGET")
    )


def cleanup_source_dir(comic_file: Path | None) -> None:
    """Best-effort cleanup of an empty or junk-only per-download source folder."""
    cleanup_dir = comic_file.parent if comic_file else None
    if not cleanup_dir or not cleanup_dir.exists():
        return

    # Safety: never remove a directory with only a few path components above
    # the filesystem root. A real per-download dir like
    # .../complete/pullbox/My Comic #1/ has many parts.
    if len(cleanup_dir.parts) <= 4:
        return

    try:
        remaining = list(cleanup_dir.iterdir())
        junk_extensions = {".nzb", ".nfo", ".txt", ".srr", ".url", ".lnk"}
        junk_only = all(
            item.is_file()
            and (item.suffix.lower() in junk_extensions or item.stat().st_size < 1024)
            for item in remaining
        )
        if not remaining or junk_only:
            shutil.rmtree(str(cleanup_dir), ignore_errors=True)
    except OSError:
        pass
