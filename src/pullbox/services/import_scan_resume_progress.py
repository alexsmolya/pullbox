"""Progress helpers for resuming Step 2 import scans."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from pullbox.schemas.import_job import ImportProgressEvent

if TYPE_CHECKING:
    from pullbox.models.import_job import ImportJobStatus

ProgressCallback = Callable[[ImportProgressEvent], Awaitable[None]]
EmitProgress = Callable[[Any, Any, ImportProgressEvent, ProgressCallback | None], Awaitable[None]]


async def emit_scan_resume_progress(
    session: Any,
    job: Any,
    *,
    status: ImportJobStatus,
    phase: str,
    progress: int,
    message: str,
    estimate_remaining_seconds: Callable[[Any, int], int | None],
    job_stats: Callable[[Any], dict[str, Any]],
    emit_progress: EmitProgress,
    maybe_slow_phase_delay: Callable[[], Awaitable[None]],
    progress_callback: ProgressCallback | None,
) -> None:
    """Emit the durable resume heartbeat shared by Step 2 resume phases."""
    if progress_callback is None:
        return

    await emit_progress(
        session,
        job,
        ImportProgressEvent(
            job_id=int(job.id),
            status=status,
            phase=phase,
            progress=progress,
            message=message,
            estimated_seconds_remaining=estimate_remaining_seconds(
                getattr(job, "scan_started_at", None),
                progress,
            ),
            **job_stats(job),
        ),
        progress_callback,
    )
    await maybe_slow_phase_delay()
