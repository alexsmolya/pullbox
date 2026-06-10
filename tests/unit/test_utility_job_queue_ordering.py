"""Tests for utility job queue ordering helpers."""

from __future__ import annotations

import pytest

from pullbox.utilities.job_queue_ordering import (
    build_resume_queue_order,
    next_queue_position,
    queued_jobs_in_order,
    resequence_queued_jobs,
)
from pullbox.utilities.models import JobState, JobType, UtilityJob


def _job(
    job_id: str,
    *,
    state: JobState = JobState.QUEUED,
    queue_position: int | None = 0,
    started_at: str | None = None,
) -> UtilityJob:
    return UtilityJob(
        id=job_id,
        job_type=JobType.FILE_CONVERT,
        display_name=f"Job {job_id}",
        state=state,
        config="{}",
        total_items=0,
        completed_items=0,
        failed_items=0,
        skipped_items=0,
        warning_count=0,
        queue_position=queue_position,
        started_at=started_at,
    )


@pytest.mark.asyncio
async def test_next_queue_position_uses_only_queued_jobs(db_session) -> None:  # type: ignore[no-untyped-def]
    db_session.add_all(
        [
            _job("queued-0", queue_position=0),
            _job("queued-4", queue_position=4),
            _job("running-99", state=JobState.RUNNING, queue_position=99),
        ]
    )
    await db_session.flush()

    assert await next_queue_position(db_session) == 5


@pytest.mark.asyncio
async def test_queued_jobs_in_order_uses_position_then_creation_then_id(db_session) -> None:  # type: ignore[no-untyped-def]
    first = _job("a-later-id", queue_position=0)
    second = _job("b-earlier-id", queue_position=0)
    third = _job("c-position-one", queue_position=1)
    db_session.add_all([third, second, first])
    await db_session.flush()

    ordered = await queued_jobs_in_order(db_session)

    assert [job.id for job in ordered] == ["a-later-id", "b-earlier-id", "c-position-one"]


def test_build_resume_queue_order_places_resumed_jobs_before_fresh_jobs() -> None:
    already_resumed = _job(
        "already-resumed",
        queue_position=0,
        started_at="2026-06-01T00:00:00+00:00",
    )
    fresh = _job("fresh", queue_position=1)
    paused = _job(
        "paused",
        state=JobState.PAUSED,
        queue_position=5,
        started_at="2026-06-01T00:05:00+00:00",
    )

    ordered = build_resume_queue_order(paused, [fresh, already_resumed])

    assert [job.id for job in ordered] == ["already-resumed", "paused", "fresh"]


@pytest.mark.asyncio
async def test_resequence_queued_jobs_rewrites_contiguous_positions(db_session) -> None:  # type: ignore[no-untyped-def]
    first = _job("first", queue_position=10)
    second = _job("second", queue_position=2)
    db_session.add_all([first, second])
    await db_session.flush()

    await resequence_queued_jobs(db_session, [first, second])

    assert first.queue_position == 0
    assert second.queue_position == 1
