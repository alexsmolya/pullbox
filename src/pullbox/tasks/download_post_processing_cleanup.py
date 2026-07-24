"""Source-folder cleanup helpers for download post-processing."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

SourceCleanupReason = Literal[
    "removed",
    "source_missing",
    "root_missing",
    "unsafe_path",
    "content_remaining",
    "error",
]


@dataclass(frozen=True)
class SourceCleanupResult:
    """Observable outcome from a source-directory cleanup attempt."""

    removed: bool
    reason: SourceCleanupReason
    error: str | None = None


def should_cleanup_source_dir(method: str, download_client: Any) -> bool:
    """Return whether post-processing may remove the source folder."""
    return (
        method == "move"
        and download_client is not None
        and str(download_client).upper() in ("SABNZBD", "NZBGET")
    )


def cleanup_source_dir(
    source_dir: Path | None,
    download_root: Path | None,
) -> SourceCleanupResult:
    """Remove an empty or junk-only job directory beneath an allowed root."""
    if source_dir is None:
        return SourceCleanupResult(removed=False, reason="source_missing")
    if download_root is None:
        return SourceCleanupResult(removed=False, reason="root_missing")

    try:
        if not source_dir.exists():
            return SourceCleanupResult(removed=False, reason="source_missing")
        if not download_root.exists() or not download_root.is_dir():
            return SourceCleanupResult(removed=False, reason="root_missing")
        if source_dir.is_symlink() or not source_dir.is_dir():
            return SourceCleanupResult(removed=False, reason="unsafe_path")

        cleanup_dir = source_dir.expanduser().resolve(strict=True)
        allowed_root = download_root.expanduser().resolve(strict=True)
        filesystem_root = Path(allowed_root.anchor)
        if (
            allowed_root == filesystem_root
            or cleanup_dir == allowed_root
            or not cleanup_dir.is_relative_to(allowed_root)
        ):
            return SourceCleanupResult(removed=False, reason="unsafe_path")

        junk_extensions = {".nzb", ".nfo", ".txt", ".srr", ".url", ".lnk"}
        for item in cleanup_dir.rglob("*"):
            if item.is_dir() and not item.is_symlink():
                continue
            if (
                item.is_symlink()
                or not item.is_file()
                or (item.suffix.lower() not in junk_extensions and item.stat().st_size >= 1024)
            ):
                return SourceCleanupResult(removed=False, reason="content_remaining")

        shutil.rmtree(str(cleanup_dir))
        if cleanup_dir.exists():
            return SourceCleanupResult(
                removed=False,
                reason="error",
                error="directory still exists after removal",
            )
        return SourceCleanupResult(removed=True, reason="removed")
    except OSError as exc:
        return SourceCleanupResult(removed=False, reason="error", error=str(exc))
