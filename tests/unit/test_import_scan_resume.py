"""Tests for Step 2 scan resume orchestration."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from pullbox.models.import_job import ImportJob, ImportJobStatus, ImportSourceType
from pullbox.services.import_scan_resume import resume_import_scan_phase

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncSession

    from pullbox.schemas.import_job import ImportProgressEvent


async def _create_job_row(
    session: AsyncSession,
    *,
    status: ImportJobStatus,
) -> ImportJob:
    job = ImportJob(
        source_path="/tmp/comics",
        source_type=ImportSourceType.FILESYSTEM,
        status=status,
        scan_started_at=datetime.now(UTC),
    )
    session.add(job)
    await session.flush()
    return job


async def _emit_progress(
    _session: AsyncSession,
    _job: ImportJob,
    event: ImportProgressEvent,
    callback: Callable[[ImportProgressEvent], Awaitable[None]] | None,
) -> None:
    if callback is not None:
        await callback(event)


@pytest.mark.asyncio
async def test_matching_resume_finishes_matching_and_file_matching(
    db_session: AsyncSession,
) -> None:
    """MATCHING resumes series matching, then continues to file matching and review."""
    job = await _create_job_row(db_session, status=ImportJobStatus.MATCHING)
    run_matching = AsyncMock()
    consolidate_groups = AsyncMock()
    run_file_matching = AsyncMock()
    progress_events: list[ImportProgressEvent] = []

    async def capture_progress(event: ImportProgressEvent) -> None:
        progress_events.append(event)

    await resume_import_scan_phase(
        db_session,
        job,
        deduplicate_series=AsyncMock(),
        run_matching=run_matching,
        consolidate_logical_series_groups=consolidate_groups,
        run_file_matching=run_file_matching,
        raise_if_cancelled=AsyncMock(),
        recompute_series_counters=AsyncMock(),
        log_event=AsyncMock(),
        emit_progress=_emit_progress,
        estimate_remaining_seconds=lambda _started_at, _progress: None,
        job_stats=lambda _job: {},
        maybe_slow_phase_delay=AsyncMock(),
        progress_callback=capture_progress,
        time_monotonic=lambda: 0.0,
        now_utc=lambda: datetime.now(UTC),
    )

    await db_session.refresh(job)
    assert job.status == ImportJobStatus.REVIEW
    assert job.match_completed_at is not None
    run_matching.assert_awaited_once()
    consolidate_groups.assert_awaited_once()
    run_file_matching.assert_awaited_once()
    assert [event.phase for event in progress_events] == [
        "matching",
        "file_matching",
        "review",
    ]
