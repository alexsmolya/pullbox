"""Timing log dispatch for Step 4 import file operations."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

LogEvent = Callable[..., Awaitable[None]]


async def log_import_file_timing_events(
    session: Any,
    *,
    job_id: int,
    source_file_name: str,
    metadata_timing: dict[str, Any] | None,
    operation_timings: list[dict[str, Any]],
    log_event: LogEvent,
) -> None:
    """Write Step 4 timing diagnostics after slow file work is complete."""
    if metadata_timing is not None:
        await log_event(
            session,
            job_id,
            "DEBUG",
            "import_file_comicinfo_metadata_timed",
            message=f"ComicInfo metadata prepared: {source_file_name}",
            **metadata_timing,
        )

    for timing in operation_timings:
        kind = timing.get("kind")
        if kind == "transfer":
            await log_event(
                session,
                job_id,
                "DEBUG",
                "import_file_transfer_timed",
                message=(
                    "File transfer completed in "
                    f"{timing.get('duration_ms')}ms: {timing.get('target_file_name')}"
                ),
                **timing,
            )
        elif kind == "cbz_comicinfo_materialize":
            await log_event(
                session,
                job_id,
                "DEBUG",
                "import_file_cbz_comicinfo_materialize_timed",
                message=(
                    "CBZ materialized with ComicInfo.xml in "
                    f"{timing.get('duration_ms')}ms: {timing.get('target_file_name')}"
                ),
                **timing,
            )
        elif kind == "comicinfo_rewrite":
            await log_event(
                session,
                job_id,
                "DEBUG",
                "import_file_comicinfo_rewrite_timed",
                message=(
                    "ComicInfo.xml archive rewrite completed in "
                    f"{timing.get('duration_ms')}ms: {timing.get('artifact_file_name')}"
                ),
                **timing,
            )
