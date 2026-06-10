"""Tests for utility dispatch finalization helpers."""

from __future__ import annotations

from typing import Any

from pullbox.utilities.base_executor import FinalizeResult, JobRunSummary, RuntimeLogEntry
from pullbox.utilities.job_queue_completion import CompletionDecision
from pullbox.utilities.job_queue_finalization import (
    finalize_dispatch_job,
    persist_completed_dispatch_log,
    persist_paused_dispatch_log,
)
from pullbox.utilities.job_queue_state import transition_job_state
from pullbox.utilities.models import JobState, JobType, UtilityJob


class _FakeSession:
    def __init__(self, job: UtilityJob | None) -> None:
        self.job = job
        self.commits = 0

    async def get(self, model: type[UtilityJob], job_id: str) -> UtilityJob | None:
        assert model is UtilityJob
        if self.job is None or self.job.id != job_id:
            return None
        return self.job

    async def commit(self) -> None:
        self.commits += 1


class _FinalizingExecutor:
    def __init__(self, finalize_result: FinalizeResult | None = None) -> None:
        self.finalize_result = finalize_result or FinalizeResult()
        self.calls = 0

    async def finalize_job(
        self,
        session: object,
        job: UtilityJob,
        summary: JobRunSummary,
        job_config: dict[str, Any],
        job_context: dict[str, Any] | None,
    ) -> FinalizeResult:
        self.calls += 1
        assert job_config == {"mode": "test"}
        assert job_context == {"context": True}
        return self.finalize_result


def test_persist_completed_dispatch_log_merges_finalize_result_and_context() -> None:
    calls: list[dict[str, Any]] = []
    session = object()
    job = UtilityJob(
        id="job-1",
        job_type=JobType.FILE_CONVERT,
        display_name="Convert",
        state=JobState.COMPLETED,
        config="{}",
        total_items=3,
        completed_items=3,
        failed_items=0,
        skipped_items=1,
        warning_count=2,
        started_at="2026-06-07T12:00:00+00:00",
        completed_at="2026-06-07T12:00:02+00:00",
    )
    summary = JobRunSummary(completed=3, failed=0, skipped=1, warnings=2)
    completion = CompletionDecision(
        target_state=JobState.COMPLETED,
        message="Job completed. 3 succeeded, 1 skipped.",
    )
    finalize_result = FinalizeResult(
        final_parts=["dry-run mode"],
        final_log_level="WARNING",
        error_message="final override",
    )

    def persist_log(active_session: object, **kwargs: Any) -> None:
        assert active_session is session
        calls.append(kwargs)

    finalization = persist_completed_dispatch_log(
        session,
        job=job,
        summary=summary,
        completion=completion,
        finalize_result=finalize_result,
        configured_level="INFO",
        persist_log=persist_log,
    )

    assert job.error_message == "final override"
    assert finalization.completion.message == "Job completed. 3 succeeded, 1 skipped, dry-run mode."
    assert finalization.completion.log_level == "WARNING"
    assert finalization.log_context == {
        "job_id": "job-1",
        "job_type": JobType.FILE_CONVERT,
        "final_state": JobState.COMPLETED,
        "completed": 3,
        "failed": 0,
        "skipped": 1,
        "warnings": 2,
        "duration_seconds": 2.0,
    }
    assert calls == [
        {
            "configured_level": "INFO",
            "job_id": "job-1",
            "level": "WARNING",
            "message": "Job completed. 3 succeeded, 1 skipped, dry-run mode.",
        }
    ]


def test_persist_paused_dispatch_log_builds_message_and_logger_context() -> None:
    calls: list[dict[str, Any]] = []
    session = object()
    summary = JobRunSummary(completed=2, failed=1, skipped=3, warnings=4)

    def persist_log(active_session: object, **kwargs: Any) -> None:
        assert active_session is session
        calls.append(kwargs)

    finalization = persist_paused_dispatch_log(
        session,
        job_id="job-1",
        summary=summary,
        configured_level="INFO",
        persist_log=persist_log,
    )

    assert finalization.message == "Job paused. 2 completed, 1 failed, 3 skipped."
    assert finalization.log_context == {
        "job_id": "job-1",
        "completed": 2,
        "failed": 1,
        "skipped": 3,
    }
    assert calls == [
        {
            "configured_level": "INFO",
            "job_id": "job-1",
            "level": "INFO",
            "message": "Job paused. 2 completed, 1 failed, 3 skipped.",
        }
    ]


async def test_finalize_dispatch_job_completes_job_and_persists_runtime_logs() -> None:
    calls: list[dict[str, Any]] = []
    session = _FakeSession(
        UtilityJob(
            id="job-1",
            job_type=JobType.FILE_CONVERT,
            display_name="Convert",
            state=JobState.RUNNING,
            config="{}",
            started_at="2026-06-07T12:00:00+00:00",
            completed_at="2026-06-07T12:00:02+00:00",
        )
    )
    summary = JobRunSummary(completed=2, failed=0, skipped=1, warnings=3)
    executor = _FinalizingExecutor(
        FinalizeResult(
            extra_logs=[RuntimeLogEntry(level="WARNING", message="Final warning")],
            final_parts=["dry-run mode"],
            final_log_level="WARNING",
        )
    )

    async def get_log_level(active_session: object) -> str:
        assert active_session is session
        return "DEBUG"

    def persist_log(active_session: object, **kwargs: Any) -> None:
        assert active_session is session
        calls.append(kwargs)

    result = await finalize_dispatch_job(
        session,
        job_id="job-1",
        job_type=JobType.FILE_CONVERT,
        executor=executor,
        summary=summary,
        config={"mode": "test"},
        job_context={"context": True},
        get_utility_log_level=get_log_level,
        persist_log=persist_log,
        transition_job=transition_job_state,
    )

    assert result.status == "completed"
    assert result.log_event == "job_dispatch_completed"
    assert result.log_context.pop("duration_seconds") > 0
    assert result.log_context == {
        "job_id": "job-1",
        "job_type": JobType.FILE_CONVERT,
        "final_state": JobState.COMPLETED,
        "completed": 2,
        "failed": 0,
        "skipped": 1,
        "warnings": 3,
    }
    assert session.commits == 1
    assert executor.calls == 1
    assert session.job is not None
    assert session.job.state == JobState.COMPLETED
    assert session.job.completed_items == 2
    assert session.job.failed_items == 0
    assert session.job.skipped_items == 1
    assert session.job.warning_count == 3
    assert summary.metadata["utility_log_level"] == "DEBUG"
    assert calls == [
        {
            "configured_level": "DEBUG",
            "job_id": "job-1",
            "item_id": None,
            "level": "WARNING",
            "message": "Final warning",
            "file_path": None,
            "extra": {},
            "worker_id": None,
            "duration_ms": None,
        },
        {
            "configured_level": "DEBUG",
            "job_id": "job-1",
            "level": "WARNING",
            "message": "Job completed. 2 succeeded, 1 skipped, dry-run mode.",
        },
    ]


async def test_finalize_dispatch_job_persists_paused_job_without_executor_finalize() -> None:
    calls: list[dict[str, Any]] = []
    session = _FakeSession(
        UtilityJob(
            id="job-1",
            job_type=JobType.FILE_CONVERT,
            display_name="Convert",
            state=JobState.PAUSED,
            config="{}",
        )
    )
    summary = JobRunSummary(completed=1, failed=2, skipped=3, warnings=4)
    executor = _FinalizingExecutor()

    async def get_log_level(active_session: object) -> str:
        assert active_session is session
        return "INFO"

    def persist_log(active_session: object, **kwargs: Any) -> None:
        assert active_session is session
        calls.append(kwargs)

    result = await finalize_dispatch_job(
        session,
        job_id="job-1",
        job_type=JobType.FILE_CONVERT,
        executor=executor,
        summary=summary,
        config={"mode": "test"},
        job_context={"context": True},
        get_utility_log_level=get_log_level,
        persist_log=persist_log,
        transition_job=transition_job_state,
    )

    assert result.status == "paused"
    assert result.log_event == "job_dispatch_paused"
    assert result.log_context == {
        "job_id": "job-1",
        "completed": 1,
        "failed": 2,
        "skipped": 3,
    }
    assert session.commits == 1
    assert executor.calls == 0
    assert calls == [
        {
            "configured_level": "INFO",
            "job_id": "job-1",
            "level": "INFO",
            "message": "Job paused. 1 completed, 2 failed, 3 skipped.",
        }
    ]


async def test_finalize_dispatch_job_returns_missing_without_commit() -> None:
    session = _FakeSession(None)
    executor = _FinalizingExecutor()

    async def get_log_level(active_session: object) -> str:
        raise AssertionError("log level should not be loaded when the job is missing")

    result = await finalize_dispatch_job(
        session,
        job_id="missing",
        job_type=JobType.FILE_CONVERT,
        executor=executor,
        summary=JobRunSummary(completed=1),
        config={"mode": "test"},
        job_context={"context": True},
        get_utility_log_level=get_log_level,
        persist_log=lambda *_args: None,
        transition_job=transition_job_state,
    )

    assert result.status == "missing"
    assert result.log_event is None
    assert result.log_context == {}
    assert session.commits == 0
    assert executor.calls == 0
