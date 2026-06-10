"""Tests for utility job API response mapping helpers."""

from __future__ import annotations

from pullbox.utilities.job_responses import (
    job_detail_to_response,
    job_to_response,
    queue_status_to_response,
)
from pullbox.utilities.models import JobState, JobType, UtilityJob


def test_job_to_response_preserves_summary_fields() -> None:
    job = UtilityJob(
        id="job-1",
        job_type=JobType.MASS_RENAME,
        display_name="Mass Rename",
        state=JobState.RUNNING,
        total_items=4,
        completed_items=1,
        failed_items=1,
        skipped_items=0,
        warning_count=2,
        queue_position=3,
        created_at="2026-06-07T12:00:00+00:00",
        started_at="2026-06-07T12:01:00+00:00",
        completed_at=None,
        created_by="adam",
        error_message=None,
        parent_job_id="parent-1",
    )

    response = job_to_response(job)

    assert response.id == "job-1"
    assert response.job_type == JobType.MASS_RENAME
    assert response.display_name == "Mass Rename"
    assert response.state == JobState.RUNNING
    assert response.total_items == 4
    assert response.completed_items == 1
    assert response.failed_items == 1
    assert response.skipped_items == 0
    assert response.warning_count == 2
    assert response.queue_position == 3
    assert response.created_at == "2026-06-07T12:00:00+00:00"
    assert response.started_at == "2026-06-07T12:01:00+00:00"
    assert response.completed_at is None
    assert response.created_by == "adam"
    assert response.error_message is None
    assert response.parent_job_id == "parent-1"
    assert response.progress_pct == 50.0


def test_job_detail_to_response_includes_config() -> None:
    job = UtilityJob(
        id="job-2",
        job_type=JobType.DB_CHECK_CLEANUP,
        display_name="Database Check",
        state=JobState.QUEUED,
        config='{"checks": ["orphans"]}',
        total_items=0,
        completed_items=0,
        failed_items=0,
        skipped_items=0,
        warning_count=0,
        queue_position=0,
    )

    response = job_detail_to_response(job)

    assert response.id == "job-2"
    assert response.config == '{"checks": ["orphans"]}'
    assert response.progress_pct == 0.0


def test_queue_status_to_response_uses_missing_counts_as_zero() -> None:
    response = queue_status_to_response(
        {
            JobState.QUEUED: 2,
            JobState.COMPLETED: 9,
        }
    )

    assert response.queued == 2
    assert response.running == 0
    assert response.paused == 0
    assert response.total_completed == 9
