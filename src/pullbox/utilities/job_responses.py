"""Utility job API response mapping helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pullbox.utilities.models import JobState, UtilityJob
from pullbox.utilities.schemas import JobDetailResponse, JobResponse, QueueStatusResponse

if TYPE_CHECKING:
    from collections.abc import Mapping


def job_to_response(job: UtilityJob) -> JobResponse:
    """Map a utility job ORM model to the public summary response."""
    return JobResponse(
        id=job.id,
        job_type=job.job_type,
        display_name=job.display_name,
        state=job.state,
        total_items=job.total_items,
        completed_items=job.completed_items,
        failed_items=job.failed_items,
        skipped_items=job.skipped_items,
        warning_count=job.warning_count,
        queue_position=job.queue_position,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        created_by=job.created_by,
        error_message=job.error_message,
        parent_job_id=job.parent_job_id,
        progress_pct=job.progress_pct,
    )


def job_detail_to_response(job: UtilityJob) -> JobDetailResponse:
    """Map a utility job ORM model to the public detail response."""
    return JobDetailResponse(
        id=job.id,
        job_type=job.job_type,
        display_name=job.display_name,
        state=job.state,
        config=job.config,
        total_items=job.total_items,
        completed_items=job.completed_items,
        failed_items=job.failed_items,
        skipped_items=job.skipped_items,
        warning_count=job.warning_count,
        queue_position=job.queue_position,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        created_by=job.created_by,
        error_message=job.error_message,
        parent_job_id=job.parent_job_id,
        progress_pct=job.progress_pct,
    )


def queue_status_to_response(counts: Mapping[str, int]) -> QueueStatusResponse:
    """Map grouped utility job state counts to the queue status response."""
    return QueueStatusResponse(
        queued=counts.get(JobState.QUEUED, 0),
        running=counts.get(JobState.RUNNING, 0),
        paused=counts.get(JobState.PAUSED, 0),
        total_completed=counts.get(JobState.COMPLETED, 0),
    )
