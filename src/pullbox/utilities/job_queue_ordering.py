"""Ordering helpers for the serial utility job queue."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select

from pullbox.utilities.models import JobState, UtilityJob

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession


async def next_queue_position(session: AsyncSession) -> int:
    """Return the next queue position for a newly queued job."""
    result = await session.execute(
        select(func.max(UtilityJob.queue_position)).where(UtilityJob.state == JobState.QUEUED)
    )
    max_pos = result.scalar_one_or_none()
    return (max_pos + 1) if max_pos is not None else 0


async def queued_jobs_in_order(session: AsyncSession) -> list[UtilityJob]:
    """Load queued jobs in their current dispatch order."""
    result = await session.execute(
        select(UtilityJob)
        .where(UtilityJob.state == JobState.QUEUED)
        .order_by(UtilityJob.queue_position, UtilityJob.created_at, UtilityJob.id)
    )
    return list(result.scalars().all())


async def resequence_queued_jobs(
    session: AsyncSession,
    ordered_jobs: Sequence[UtilityJob],
) -> None:
    """Rewrite queue positions to a contiguous 0..N ordering."""
    for idx, queued_job in enumerate(ordered_jobs):
        queued_job.queue_position = idx
    await session.flush()


def build_resume_queue_order(
    resumed_job: UtilityJob,
    queued_jobs: Sequence[UtilityJob],
) -> list[UtilityJob]:
    """Place a resumed job after already-resumed work but before fresh queued jobs."""
    resumed_priority_jobs = [queued_job for queued_job in queued_jobs if queued_job.started_at]
    fresh_jobs = [queued_job for queued_job in queued_jobs if not queued_job.started_at]
    return [*resumed_priority_jobs, resumed_job, *fresh_jobs]
