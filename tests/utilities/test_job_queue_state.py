"""Tests for utility job queue state-machine helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pullbox.utilities.job_queue_state import (
    TERMINAL_STATES,
    job_duration_seconds,
    transition_job_state,
)
from pullbox.utilities.models import JobState, JobType, UtilityJob


def _job(state: JobState) -> UtilityJob:
    return UtilityJob(
        id="state-test-job",
        job_type=JobType.FILE_CONVERT,
        display_name="State Test",
        state=state,
        config="{}",
        total_items=0,
        completed_items=0,
        failed_items=0,
        skipped_items=0,
        warning_count=0,
        queue_position=7,
    )


def test_transition_job_state_updates_running_timestamp() -> None:
    job = _job(JobState.QUEUED)

    old_state = transition_job_state(job, JobState.RUNNING)

    assert old_state == JobState.QUEUED
    assert job.state == JobState.RUNNING
    assert job.started_at is not None
    assert job.queue_position == 7


def test_transition_job_state_clears_queue_position_for_terminal_state() -> None:
    job = _job(JobState.RUNNING)

    transition_job_state(job, JobState.COMPLETED)

    assert JobState.COMPLETED in TERMINAL_STATES
    assert job.state == JobState.COMPLETED
    assert job.completed_at is not None
    assert job.queue_position is None


def test_transition_job_state_rejects_invalid_transition() -> None:
    job = _job(JobState.FAILED)

    with pytest.raises(ValueError, match="Invalid transition"):
        transition_job_state(job, JobState.RUNNING)


def test_job_duration_seconds_rounds_non_negative_duration() -> None:
    job = _job(JobState.COMPLETED)
    started = datetime.now(UTC)
    completed = started + timedelta(seconds=1.2349)
    job.started_at = started.isoformat()
    job.completed_at = completed.isoformat()

    assert job_duration_seconds(job) == 1.235
