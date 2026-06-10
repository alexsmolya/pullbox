"""Tests for utility job construction helpers."""

from __future__ import annotations

import json

from pullbox.utilities.job_queue_creation import build_queued_job, build_rollback_job
from pullbox.utilities.models import JobState, JobType, UtilityJob


def test_build_queued_job_initializes_counters_and_config_json() -> None:
    job = build_queued_job(
        job_type=JobType.FILE_CONVERT,
        display_name="Convert files",
        config={"target_format": "cbz"},
        queue_position=3,
        created_by="admin",
        job_id="job-id",
        created_at="2026-06-07T12:00:00+00:00",
    )

    assert job.id == "job-id"
    assert job.job_type == JobType.FILE_CONVERT
    assert job.display_name == "Convert files"
    assert job.state == JobState.QUEUED
    assert json.loads(job.config) == {"target_format": "cbz"}
    assert job.queue_position == 3
    assert job.created_by == "admin"
    assert job.created_at == "2026-06-07T12:00:00+00:00"
    assert job.completed_items == 0
    assert job.failed_items == 0
    assert job.skipped_items == 0
    assert job.warning_count == 0


def test_build_rollback_job_links_to_parent_job() -> None:
    parent = UtilityJob(
        id="parent-id",
        job_type=JobType.FILE_CONVERT,
        display_name="Convert files",
        state=JobState.COMPLETED,
        config="{}",
        total_items=2,
        completed_items=2,
        failed_items=0,
        skipped_items=0,
        warning_count=0,
    )

    rollback = build_rollback_job(
        parent,
        queue_position=4,
        created_by="admin",
        job_id="rollback-id",
        created_at="2026-06-07T12:30:00+00:00",
    )

    assert rollback.id == "rollback-id"
    assert rollback.job_type == JobType.ROLLBACK
    assert rollback.display_name == "Rollback: Convert files"
    assert rollback.state == JobState.QUEUED
    assert json.loads(rollback.config) == {"parent_job_id": "parent-id"}
    assert rollback.queue_position == 4
    assert rollback.created_by == "admin"
    assert rollback.parent_job_id == "parent-id"
    assert rollback.total_items == 0
