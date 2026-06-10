"""Diagnostic log file collection helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from pathlib import Path

logger = structlog.get_logger(__name__)

MAX_LOG_FILE_BYTES = 10 * 1024 * 1024
LOG_DAYS = 5


def collect_log_files(logs_dir: Path) -> list[tuple[str, bytes]]:
    """Read log files from the last N days, truncating large files."""
    if not logs_dir.is_dir():
        return []

    cutoff = datetime.now(UTC) - timedelta(days=LOG_DAYS)
    files: list[tuple[str, bytes]] = []

    for path in sorted(logs_dir.glob("*.log*")):
        if not path.is_file():
            continue
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
            if mtime < cutoff:
                continue

            size = path.stat().st_size
            if size > MAX_LOG_FILE_BYTES:
                with open(path, "rb") as fh:
                    fh.seek(max(0, size - MAX_LOG_FILE_BYTES))
                    content = b"[... truncated ...]\n" + fh.read()
            else:
                content = path.read_bytes()

            files.append((path.name, content))
        except OSError:
            logger.debug("diagnostic_log_read_failed", path=str(path))
            continue

    return files
