"""Tests for utility dispatch runtime-state helpers."""

from __future__ import annotations

import pytest

from pullbox.utilities.job_queue_config import (
    DEFAULT_UTILITY_LOG_LEVEL,
    DEFAULT_UTILITY_WORKER_COUNT,
)
from pullbox.utilities.job_queue_runtime_state import (
    apply_job_counter_snapshot,
    build_dispatch_runtime_state,
    load_dispatch_runtime_state,
)
from pullbox.utilities.models import JobState, JobType, UtilityJob


def _job() -> UtilityJob:
    return UtilityJob(
        id="job-1",
        job_type=JobType.FILE_CONVERT,
        display_name="Convert",
        state=JobState.RUNNING,
        config="{}",
        total_items=10,
        completed_items=3,
        failed_items=2,
        skipped_items=1,
        warning_count=4,
    )


def test_build_dispatch_runtime_state_defaults_without_current_job() -> None:
    runtime = build_dispatch_runtime_state(
        job_id="job-1",
        job_type=JobType.FILE_CONVERT,
        current_job=None,
    )

    assert runtime.worker_count == DEFAULT_UTILITY_WORKER_COUNT
    assert runtime.utility_log_level == DEFAULT_UTILITY_LOG_LEVEL
    assert runtime.summary.completed == 0
    assert runtime.summary.failed == 0
    assert runtime.summary.skipped == 0
    assert runtime.summary.warnings == 0
    assert runtime.summary.metadata == {
        "job_id": "job-1",
        "job_type": JobType.FILE_CONVERT,
        "utility_log_level": DEFAULT_UTILITY_LOG_LEVEL,
    }


def test_build_dispatch_runtime_state_restores_counters_and_settings() -> None:
    runtime = build_dispatch_runtime_state(
        job_id="job-1",
        job_type=JobType.FILE_CONVERT,
        current_job=_job(),
        worker_count=2,
        utility_log_level="WARNING",
    )

    assert runtime.worker_count == 2
    assert runtime.utility_log_level == "WARNING"
    assert runtime.summary.completed == 3
    assert runtime.summary.failed == 2
    assert runtime.summary.skipped == 1
    assert runtime.summary.warnings == 4
    assert runtime.summary.metadata == {
        "job_id": "job-1",
        "job_type": JobType.FILE_CONVERT,
        "utility_log_level": "WARNING",
    }


def test_apply_job_counter_snapshot_updates_persisted_counters() -> None:
    job = _job()

    apply_job_counter_snapshot(
        job,
        completed=7,
        failed=1,
        skipped=2,
        warnings=3,
    )

    assert job.completed_items == 7
    assert job.failed_items == 1
    assert job.skipped_items == 2
    assert job.warning_count == 3


class FakeSession:
    def __init__(self, job: UtilityJob | None) -> None:
        self.job = job

    async def get(self, model: type[object], item_id: str) -> object | None:
        assert model is UtilityJob
        assert item_id == "job-1"
        return self.job


async def _worker_count(_session: object) -> int:
    return 6


async def _log_level(_session: object) -> str:
    return "WARNING"


async def _unexpected_worker_count(_session: object) -> int:
    raise AssertionError("worker count should not be loaded without a job")


async def _unexpected_log_level(_session: object) -> str:
    raise AssertionError("log level should not be loaded without a job")


@pytest.mark.asyncio
async def test_load_dispatch_runtime_state_loads_persisted_job_settings() -> None:
    runtime = await load_dispatch_runtime_state(
        FakeSession(_job()),
        job_id="job-1",
        job_type=JobType.FILE_CONVERT,
        get_worker_count=_worker_count,
        get_utility_log_level=_log_level,
    )

    assert runtime.worker_count == 6
    assert runtime.utility_log_level == "WARNING"
    assert runtime.summary.completed == 3
    assert runtime.summary.failed == 2
    assert runtime.summary.skipped == 1
    assert runtime.summary.warnings == 4


@pytest.mark.asyncio
async def test_load_dispatch_runtime_state_uses_defaults_when_job_missing() -> None:
    runtime = await load_dispatch_runtime_state(
        FakeSession(None),
        job_id="job-1",
        job_type=JobType.FILE_CONVERT,
        get_worker_count=_unexpected_worker_count,
        get_utility_log_level=_unexpected_log_level,
    )

    assert runtime.worker_count == DEFAULT_UTILITY_WORKER_COUNT
    assert runtime.utility_log_level == DEFAULT_UTILITY_LOG_LEVEL
    assert runtime.summary.completed == 0
    assert runtime.summary.failed == 0
