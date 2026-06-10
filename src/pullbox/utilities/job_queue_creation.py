"""Utility job construction helpers."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any

from pullbox.utilities.models import JobState, JobType, UtilityJob


def _new_job_id() -> str:
    return os.urandom(16).hex()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def build_queued_job(
    *,
    job_type: str,
    display_name: str,
    config: dict[str, Any],
    queue_position: int,
    created_by: str | None = None,
    job_id: str | None = None,
    created_at: str | None = None,
) -> UtilityJob:
    """Build a queued utility job with standard counters/defaults."""
    return UtilityJob(
        id=job_id or _new_job_id(),
        job_type=job_type,
        display_name=display_name,
        state=JobState.QUEUED,
        config=json.dumps(config),
        total_items=0,
        completed_items=0,
        failed_items=0,
        skipped_items=0,
        warning_count=0,
        queue_position=queue_position,
        created_at=created_at or _now_iso(),
        created_by=created_by,
    )


def build_rollback_job(
    parent_job: UtilityJob,
    *,
    queue_position: int,
    created_by: str | None = None,
    job_id: str | None = None,
    created_at: str | None = None,
) -> UtilityJob:
    """Build a queued rollback child job for a parent utility job."""
    return UtilityJob(
        id=job_id or _new_job_id(),
        job_type=JobType.ROLLBACK,
        display_name=f"Rollback: {parent_job.display_name}",
        state=JobState.QUEUED,
        config=json.dumps({"parent_job_id": parent_job.id}),
        total_items=0,
        completed_items=0,
        failed_items=0,
        skipped_items=0,
        warning_count=0,
        queue_position=queue_position,
        created_at=created_at or _now_iso(),
        created_by=created_by,
        parent_job_id=parent_job.id,
    )
