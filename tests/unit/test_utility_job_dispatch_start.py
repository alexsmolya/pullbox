"""Tests for utility job dispatch-start helpers."""

from __future__ import annotations

from typing import Any

import pytest

from pullbox.utilities.job_queue_dispatch_start import (
    load_next_dispatch_candidate,
    mark_job_started,
    mark_job_without_executor,
    persist_started_dispatch_job,
    snapshot_started_job,
    start_next_dispatch_job,
)
from pullbox.utilities.models import JobState, JobType, UtilityJob


def _job(
    job_id: str,
    *,
    state: JobState = JobState.QUEUED,
    job_type: str = JobType.FILE_CONVERT,
    queue_position: int | None = 0,
    created_at: str | None = None,
) -> UtilityJob:
    return UtilityJob(
        id=job_id,
        job_type=job_type,
        display_name=f"Job {job_id}",
        state=state,
        config='{"count": 1}',
        total_items=0,
        completed_items=0,
        failed_items=0,
        skipped_items=0,
        warning_count=0,
        queue_position=queue_position,
        created_at=created_at,
    )


class FakeSession:
    def __init__(self) -> None:
        self.commit_count = 0

    async def commit(self) -> None:
        self.commit_count += 1


@pytest.mark.asyncio
async def test_load_next_dispatch_candidate_stops_when_job_is_running(db_session) -> None:  # type: ignore[no-untyped-def]
    queued = _job("queued", queue_position=0)
    running = _job("running", state=JobState.RUNNING, queue_position=None)
    db_session.add_all([queued, running])
    await db_session.flush()

    assert await load_next_dispatch_candidate(db_session) is None


@pytest.mark.asyncio
async def test_load_next_dispatch_candidate_uses_queue_order(db_session) -> None:  # type: ignore[no-untyped-def]
    later = _job("later", queue_position=2, created_at="2026-06-07T12:00:00+00:00")
    first = _job("first", queue_position=0, created_at="2026-06-07T12:10:00+00:00")
    tie = _job("tie", queue_position=0, created_at="2026-06-07T12:10:00+00:00")
    db_session.add_all([later, tie, first])
    await db_session.flush()

    candidate = await load_next_dispatch_candidate(db_session)

    assert candidate is not None
    assert candidate.id == "first"


def test_mark_job_without_executor_preserves_failed_job_fields() -> None:
    job = _job("missing-executor", job_type="missing")

    mark_job_without_executor(job, completed_at="2026-06-07T12:00:00+00:00")

    assert job.state == JobState.FAILED
    assert job.error_message == "No executor registered for job type: missing"
    assert job.completed_at == "2026-06-07T12:00:00+00:00"


def test_mark_job_started_transitions_to_running_and_clears_queue_position() -> None:
    job = _job("start-me", queue_position=3)

    mark_job_started(job, started_at="2026-06-07T12:00:00+00:00")

    assert job.state == JobState.RUNNING
    assert job.started_at == "2026-06-07T12:00:00+00:00"
    assert job.queue_position is None


def test_mark_job_started_enforces_state_machine() -> None:
    job = _job("already-done", state=JobState.COMPLETED)

    with pytest.raises(ValueError, match="Invalid transition"):
        mark_job_started(job, started_at="2026-06-07T12:00:00+00:00")


def test_snapshot_started_job_captures_dispatch_runtime_fields() -> None:
    job = _job("queued", job_type=JobType.INTEGRITY_CHECK)
    executor = object()

    started = snapshot_started_job(job, executor)

    assert started.job_id == "queued"
    assert started.job_type == JobType.INTEGRITY_CHECK
    assert started.display_name == "Job queued"
    assert started.raw_config == '{"count": 1}'
    assert started.executor is executor


@pytest.mark.asyncio
async def test_persist_started_dispatch_job_marks_started_logs_and_snapshots() -> None:
    calls: list[dict[str, Any]] = []
    session = FakeSession()
    job = _job("queued", queue_position=2)
    executor = object()

    def persist_log(active_session: object, **kwargs: Any) -> None:
        assert active_session is session
        calls.append(kwargs)

    started = await persist_started_dispatch_job(
        session,
        job=job,
        executor=executor,
        utility_log_level="INFO",
        persist_log=persist_log,
        started_at="2026-06-07T12:00:00+00:00",
    )

    assert job.state == JobState.RUNNING
    assert job.started_at == "2026-06-07T12:00:00+00:00"
    assert job.queue_position is None
    assert session.commit_count == 1
    assert started.started_job.job_id == "queued"
    assert started.started_job.executor is executor
    assert started.log_context == {
        "job_id": "queued",
        "job_type": JobType.FILE_CONVERT,
        "display_name": "Job queued",
    }
    assert calls == [
        {
            "configured_level": "INFO",
            "job_id": "queued",
            "level": "INFO",
            "message": "Job started: Job queued",
        }
    ]


@pytest.mark.asyncio
async def test_start_next_dispatch_job_returns_idle_when_queue_has_no_candidate(db_session) -> None:  # type: ignore[no-untyped-def]
    calls: list[dict[str, Any]] = []

    async def get_log_level(_session: object) -> str:
        raise AssertionError("log level should not be loaded when no job can start")

    result = await start_next_dispatch_job(
        db_session,
        get_executor=lambda _job_type: object(),
        get_utility_log_level=get_log_level,
        persist_log=lambda _session, **kwargs: calls.append(kwargs),
        timestamp_factory=lambda: "2026-06-07T12:00:00+00:00",
    )

    assert result.status == "idle"
    assert result.started_job is None
    assert result.log_event is None
    assert result.log_context == {}
    assert calls == []


@pytest.mark.asyncio
async def test_start_next_dispatch_job_marks_missing_executor_failed(db_session) -> None:  # type: ignore[no-untyped-def]
    job = _job("queued", job_type="missing-executor")
    db_session.add(job)
    await db_session.flush()

    async def get_log_level(_session: object) -> str:
        raise AssertionError("log level should not be loaded without an executor")

    result = await start_next_dispatch_job(
        db_session,
        get_executor=lambda _job_type: None,
        get_utility_log_level=get_log_level,
        persist_log=lambda *_args, **_kwargs: None,
        timestamp_factory=lambda: "2026-06-07T12:00:00+00:00",
    )

    await db_session.refresh(job)

    assert result.status == "missing_executor"
    assert result.started_job is None
    assert result.log_event is None
    assert result.log_context == {}
    assert job.state == JobState.FAILED
    assert job.error_message == "No executor registered for job type: missing-executor"
    assert job.completed_at == "2026-06-07T12:00:00+00:00"


@pytest.mark.asyncio
async def test_start_next_dispatch_job_persists_started_candidate(db_session) -> None:  # type: ignore[no-untyped-def]
    calls: list[dict[str, Any]] = []
    job = _job("queued", queue_position=1)
    executor = object()
    db_session.add(job)
    await db_session.flush()

    async def get_log_level(active_session: object) -> str:
        assert active_session is db_session
        return "DEBUG"

    def persist_log(active_session: object, **kwargs: Any) -> None:
        assert active_session is db_session
        calls.append(kwargs)

    result = await start_next_dispatch_job(
        db_session,
        get_executor=lambda job_type: executor if job_type == JobType.FILE_CONVERT else None,
        get_utility_log_level=get_log_level,
        persist_log=persist_log,
        timestamp_factory=lambda: "2026-06-07T12:00:00+00:00",
    )

    await db_session.refresh(job)

    assert result.status == "started"
    assert result.started_job is not None
    assert result.started_job.job_id == "queued"
    assert result.started_job.executor is executor
    assert result.log_event == "job_dispatch_started"
    assert result.log_context == {
        "job_id": "queued",
        "job_type": JobType.FILE_CONVERT,
        "display_name": "Job queued",
    }
    assert job.state == JobState.RUNNING
    assert job.queue_position is None
    assert calls == [
        {
            "configured_level": "DEBUG",
            "job_id": "queued",
            "level": "INFO",
            "message": "Job started: Job queued",
        }
    ]
