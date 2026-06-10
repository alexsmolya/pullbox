"""System log file helpers for the system API."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from pullbox.core.exceptions import NotFoundError, ValidationError

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path


class LogFileResponse(BaseModel):
    """Details about a log file."""

    filename: str
    size_bytes: int
    modified_at: str


class LogContentResponse(BaseModel):
    """Contents of a log file."""

    filename: str
    total_lines: int
    lines: list[str]
    truncated: bool = False


_SAFE_FILENAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,254}$")


def validate_safe_filename(filename: str) -> bool:
    """Validate that a filename is safe for filesystem operations."""
    if not filename or len(filename) > 255:
        return False
    if ".." in filename:
        return False
    if "/" in filename or "\\" in filename:
        return False
    return bool(_SAFE_FILENAME_RE.match(filename))


def is_valid_log_path(logs_dir: Path, path: Path) -> bool:
    """Verify a path is a valid log file inside the logs directory."""
    try:
        resolved = path.resolve()
        dir_resolved = logs_dir.resolve()
        return resolved.parent == dir_resolved and ".log" in resolved.name and resolved.is_file()
    except (OSError, ValueError):
        return False


def _validated_log_path(logs_dir: Path, filename: str) -> Path:
    if not validate_safe_filename(filename):
        raise ValidationError(f"Invalid log filename: {filename}")
    path = logs_dir / filename
    if not is_valid_log_path(logs_dir, path):
        raise NotFoundError("Log file", filename)
    return path


def list_log_file_responses(logs_dir: Path) -> list[LogFileResponse]:
    """List all log files in newest-first order."""
    if not logs_dir.is_dir():
        return []

    files: list[LogFileResponse] = []
    for path in sorted(logs_dir.glob("*.log*"), key=lambda p: p.stat().st_mtime, reverse=True):
        if not path.is_file():
            continue
        stat = path.stat()
        files.append(
            LogFileResponse(
                filename=path.name,
                size_bytes=stat.st_size,
                modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
            )
        )
    return files


def read_log_content(logs_dir: Path, filename: str, *, tail: int) -> LogContentResponse:
    """Return the tail of a log file."""
    path = _validated_log_path(logs_dir, filename)

    text = path.read_text(encoding="utf-8", errors="replace")
    all_lines = text.splitlines()
    total = len(all_lines)
    truncated = total > tail
    lines = all_lines[-tail:] if truncated else all_lines

    return LogContentResponse(
        filename=filename,
        total_lines=total,
        lines=lines,
        truncated=truncated,
    )


def build_log_download_response(logs_dir: Path, filename: str) -> FileResponse:
    """Build a safe log-file download response."""
    path = _validated_log_path(logs_dir, filename)
    return FileResponse(
        path=str(path),
        media_type="text/plain",
        filename=filename,
    )


def delete_log_path(logs_dir: Path, filename: str) -> dict[str, str]:
    """Delete one validated log file."""
    path = _validated_log_path(logs_dir, filename)
    path.unlink()
    return {"message": f"Log file deleted: {filename}"}


def clear_log_paths(logs_dir: Path) -> dict[str, str]:
    """Delete all log files under the runtime logs directory."""
    if not logs_dir.is_dir():
        return {"message": "No log files to clear."}

    deleted = 0
    for path in logs_dir.glob("*.log*"):
        if path.is_file():
            path.unlink()
            deleted += 1

    return {"message": f"Cleared {deleted} log file{'s' if deleted != 1 else ''}."}


def matches_level(line: str, level_filter: str) -> bool:
    """Check if a log line matches the requested level filter."""
    if level_filter == "all":
        return True
    lower = line.lower()
    if level_filter == "error":
        return any(
            marker in lower
            for marker in (
                '"level": "error"',
                '"level":"error"',
                "[error]",
                "level=error",
                '"level": "critical"',
                '"level":"critical"',
                "[critical]",
                "level=critical",
            )
        )
    return any(
        marker in lower
        for marker in (
            f'"level": "{level_filter}"',
            f'"level":"{level_filter}"',
            f"[{level_filter}]",
            f"level={level_filter}",
        )
    )


async def iter_log_stream_events(
    path: Path,
    request: Any,
    *,
    level: str,
) -> AsyncGenerator[str, None]:
    """Yield SSE payloads for existing and newly appended log lines."""
    file_size = path.stat().st_size if path.exists() else 0

    if path.exists():
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()[-50:]
        for line in lines:
            if matches_level(line, level):
                yield f"data: {json.dumps({'line': line})}\n\n"

    while True:
        if await request.is_disconnected():
            break

        await asyncio.sleep(1.0)

        if not path.exists():
            continue

        current_size = path.stat().st_size
        if current_size <= file_size:
            if current_size < file_size:
                file_size = 0
            else:
                yield 'data: {"heartbeat": true}\n\n'
                continue

        with open(path, encoding="utf-8", errors="replace") as fh:
            fh.seek(file_size)
            new_text = fh.read()

        file_size = current_size
        for line in new_text.splitlines():
            if line.strip() and matches_level(line, level):
                yield f"data: {json.dumps({'line': line})}\n\n"


def build_log_stream_response(
    logs_dir: Path,
    filename: str,
    request: Any,
    *,
    level: str,
) -> StreamingResponse:
    """Build an SSE response for a validated log file."""
    path = _validated_log_path(logs_dir, filename)
    return StreamingResponse(
        iter_log_stream_events(path, request, level=level),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
