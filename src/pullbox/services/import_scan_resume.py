"""Step 2 scan resume orchestration."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pullbox.models.import_job import ImportJobStatus
from pullbox.schemas.import_job import ImportProgressEvent
from pullbox.services.import_scan_resume_progress import emit_scan_resume_progress
from pullbox.services.import_workflow_state import (
    SCAN_PROGRESS_ANALYZE_START,
    SCAN_PROGRESS_FILE_MATCH_START,
    SCAN_PROGRESS_MATCH_START,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncSession

    from pullbox.models.import_job import ImportJob

    ProgressCallback = Callable[[ImportProgressEvent], Awaitable[None]]
    ResumePhaseFunc = Callable[..., Awaitable[Any]]
    RecomputeSeriesCountersFunc = Callable[[AsyncSession, ImportJob], Awaitable[None]]
    RaiseIfCancelledFunc = Callable[[AsyncSession, int], Awaitable[None]]
    LogEventFunc = Callable[..., Awaitable[None]]
    EmitProgressFunc = Callable[
        [AsyncSession, ImportJob, ImportProgressEvent, ProgressCallback | None],
        Awaitable[None],
    ]
    EstimateRemainingFunc = Callable[[datetime | None, int], int | None]
    JobStatsFunc = Callable[[ImportJob], dict[str, Any]]
    SlowPhaseDelayFunc = Callable[[], Awaitable[None]]


RESUMABLE_SCAN_STATUSES = frozenset(
    {
        ImportJobStatus.ANALYZING,
        ImportJobStatus.MATCHING,
        ImportJobStatus.FILE_MATCHING,
    }
)


def _now_utc() -> datetime:
    return datetime.now(UTC)


async def resume_import_scan_phase(
    session: AsyncSession,
    job: ImportJob,
    *,
    deduplicate_series: ResumePhaseFunc,
    run_matching: ResumePhaseFunc,
    consolidate_logical_series_groups: ResumePhaseFunc,
    run_file_matching: ResumePhaseFunc,
    raise_if_cancelled: RaiseIfCancelledFunc,
    recompute_series_counters: RecomputeSeriesCountersFunc,
    log_event: LogEventFunc,
    emit_progress: EmitProgressFunc,
    estimate_remaining_seconds: EstimateRemainingFunc,
    job_stats: JobStatsFunc,
    maybe_slow_phase_delay: SlowPhaseDelayFunc,
    progress_callback: ProgressCallback | None = None,
    time_monotonic: Callable[[], float] = time.monotonic,
    now_utc: Callable[[], datetime] = _now_utc,
) -> None:
    """Resume a Step 2 scan from ANALYZING, MATCHING, or FILE_MATCHING."""
    job_id = int(job.id)
    analyze_duration_ms = 0
    series_matching_duration_ms = 0
    file_matching_duration_ms = 0
    resumed_started_at = time_monotonic()

    job.scan_started_at = job.scan_started_at or now_utc()
    await log_event(
        session,
        job_id,
        "INFO",
        "import_scan_phase_resumed",
        message=f"Resuming Step 2 from {job.status.value}",
        phase=job.status.value,
    )

    if job.status == ImportJobStatus.ANALYZING:
        await session.commit()

        await emit_scan_resume_progress(
            session,
            job,
            status=ImportJobStatus.ANALYZING,
            phase="analyzing",
            progress=SCAN_PROGRESS_ANALYZE_START,
            message="Resuming duplicate analysis...",
            estimate_remaining_seconds=estimate_remaining_seconds,
            job_stats=job_stats,
            emit_progress=emit_progress,
            maybe_slow_phase_delay=maybe_slow_phase_delay,
            progress_callback=progress_callback,
        )

        analyze_started_at = time_monotonic()
        await deduplicate_series(session, job, progress_callback=progress_callback)
        analyze_duration_ms = round((time_monotonic() - analyze_started_at) * 1000)
        await recompute_series_counters(session, job)
        await raise_if_cancelled(session, job_id)

        job.status = ImportJobStatus.MATCHING
        job.match_started_at = now_utc()
        await session.commit()

    if job.status == ImportJobStatus.MATCHING:
        job.match_started_at = job.match_started_at or now_utc()
        await session.commit()

        await emit_scan_resume_progress(
            session,
            job,
            status=ImportJobStatus.MATCHING,
            phase="matching",
            progress=SCAN_PROGRESS_MATCH_START,
            message="Resuming ComicVine matching...",
            estimate_remaining_seconds=estimate_remaining_seconds,
            job_stats=job_stats,
            emit_progress=emit_progress,
            maybe_slow_phase_delay=maybe_slow_phase_delay,
            progress_callback=progress_callback,
        )

        series_matching_started_at = time_monotonic()
        await run_matching(session, job, progress_callback=progress_callback)
        await raise_if_cancelled(session, job_id)

        await consolidate_logical_series_groups(session, job)
        series_matching_duration_ms = round((time_monotonic() - series_matching_started_at) * 1000)
        await raise_if_cancelled(session, job_id)

        job.match_completed_at = now_utc()
        job.status = ImportJobStatus.FILE_MATCHING
        await session.commit()

    if job.status == ImportJobStatus.FILE_MATCHING:
        await emit_scan_resume_progress(
            session,
            job,
            status=ImportJobStatus.FILE_MATCHING,
            phase="file_matching",
            progress=SCAN_PROGRESS_FILE_MATCH_START,
            message="Resuming file-to-issue matching...",
            estimate_remaining_seconds=estimate_remaining_seconds,
            job_stats=job_stats,
            emit_progress=emit_progress,
            maybe_slow_phase_delay=maybe_slow_phase_delay,
            progress_callback=progress_callback,
        )

        file_matching_started_at = time_monotonic()
        await run_file_matching(session, job, progress_callback=progress_callback)
        file_matching_duration_ms = round((time_monotonic() - file_matching_started_at) * 1000)
        await raise_if_cancelled(session, job_id)

        job.status = ImportJobStatus.REVIEW
        await log_event(
            session,
            job_id,
            "INFO",
            "import_step2_timing",
            message="Step 2 resume timing metrics collected",
            scan_duration_ms=0,
            analyze_duration_ms=analyze_duration_ms,
            series_matching_duration_ms=series_matching_duration_ms,
            file_matching_duration_ms=file_matching_duration_ms,
            total_duration_ms=round((time_monotonic() - resumed_started_at) * 1000),
        )
        await log_event(
            session,
            job_id,
            "INFO",
            "import_ready_for_review",
            message="All phases complete, ready for user review",
            series_matched=job.series_matched,
            series_duplicate=job.series_duplicate,
            series_no_match=job.series_no_match,
        )
        await session.commit()

        if progress_callback:
            await emit_progress(
                session,
                job,
                ImportProgressEvent(
                    job_id=job_id,
                    status=ImportJobStatus.REVIEW,
                    phase="review",
                    progress=100,
                    message="Ready for review",
                    **job_stats(job),
                ),
                progress_callback,
            )
            await maybe_slow_phase_delay()
