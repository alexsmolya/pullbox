"""Tests for utility processed-item persistence helpers."""

from __future__ import annotations

from typing import Any

import pytest

from pullbox.utilities.base_executor import (
    ApplyResult,
    ItemResult,
    JobRunSummary,
    ProcessedItem,
    RuntimeLogEntry,
)
from pullbox.utilities.job_queue_item_persistence import (
    persist_post_commit_logs,
    persist_processed_item_failure,
    persist_processed_item_result,
)
from pullbox.utilities.models import JobState, JobType, UtilityJob, UtilityJobItem


class FakeSession:
    def __init__(
        self,
        *,
        job: UtilityJob | None,
        item: UtilityJobItem | None,
    ) -> None:
        self.job = job
        self.item = item

    async def get(self, model: type[Any], item_id: str) -> Any:
        if model is UtilityJob:
            assert item_id == "job-1"
            return self.job
        if model is UtilityJobItem:
            assert item_id == "item-1"
            return self.item
        raise AssertionError(f"Unexpected model lookup: {model}")


class RecordingExecutor:
    def __init__(self, apply_result: ApplyResult) -> None:
        self.apply_result = apply_result
        self.calls: list[tuple[Any, ...]] = []

    async def apply_item_result(
        self,
        session: FakeSession,
        item: UtilityJobItem,
        payload_data: dict[str, Any],
        processed: ProcessedItem,
        job_config: dict[str, Any],
        job_context: dict[str, Any] | None,
        summary: JobRunSummary,
    ) -> ApplyResult:
        self.calls.append(
            (
                session,
                item,
                payload_data,
                processed,
                job_config,
                job_context,
                summary,
            )
        )
        return self.apply_result


def _job() -> UtilityJob:
    return UtilityJob(
        id="job-1",
        job_type=JobType.FILE_CONVERT,
        display_name="Convert",
        state=JobState.RUNNING,
        config="{}",
        total_items=5,
        completed_items=2,
        failed_items=1,
        skipped_items=0,
        warning_count=1,
    )


def _item() -> UtilityJobItem:
    return UtilityJobItem(
        id="item-1",
        job_id="job-1",
        item_index=0,
        state="IN_PROGRESS",
        file_path="/imports/item.cbr",
        operation="convert",
    )


@pytest.mark.asyncio
async def test_persist_processed_item_result_applies_snapshot_logs_and_counters() -> None:
    calls: list[dict[str, Any]] = []
    job = _job()
    item = _item()
    session = FakeSession(job=job, item=item)
    summary = JobRunSummary(completed=2, failed=1, skipped=0, warnings=1)
    processed = ProcessedItem(
        item_id="item-1",
        result=ItemResult.COMPLETED,
        before_state={"source": "/imports/item.cbr"},
        after_state={"target": "/comics/item.cbz"},
        duration_ms=123,
        worker_id=4,
        log_entries=[("INFO", "worker detail", {"step": "convert"})],
    )
    apply_result = ApplyResult(
        extra_logs=[
            RuntimeLogEntry(level="WARNING", message="apply detail", extra={"step": "apply"})
        ],
        warning_increment=2,
        warning_message="apply warning",
    )
    executor = RecordingExecutor(apply_result)

    def persist_log(active_session: object, **kwargs: Any) -> None:
        assert active_session is session
        calls.append(kwargs)

    result = await persist_processed_item_result(
        session,
        job_id="job-1",
        item_id="item-1",
        file_path="/imports/item.cbr",
        processed=processed,
        payload_data={"file_path": "/imports/item.cbr"},
        executor=executor,
        config={"target": "cbz"},
        job_context={"ready": True},
        summary=summary,
        configured_level="INFO",
        persist_log=persist_log,
        completed_at="2026-06-07T12:00:00+00:00",
    )

    assert result is not None
    assert result.apply_result is apply_result
    assert result.completed_delta == 1
    assert result.failed_delta == 0
    assert result.skipped_delta == 0
    assert result.warning_delta == 2
    assert item.state == "COMPLETED"
    assert item.duration_ms == 123
    assert item.warning_message == "apply warning"
    assert item.worker_id == 4
    assert item.completed_at == "2026-06-07T12:00:00+00:00"
    assert job.completed_items == 3
    assert job.failed_items == 1
    assert job.skipped_items == 0
    assert job.warning_count == 3
    assert executor.calls == [
        (
            session,
            item,
            {"file_path": "/imports/item.cbr"},
            processed,
            {"target": "cbz"},
            {"ready": True},
            summary,
        )
    ]
    assert calls == [
        {
            "configured_level": "INFO",
            "job_id": "job-1",
            "item_id": "item-1",
            "level": "INFO",
            "message": "worker detail",
            "file_path": "/imports/item.cbr",
            "extra": {"step": "convert"},
            "worker_id": 4,
            "duration_ms": 123,
        },
        {
            "configured_level": "INFO",
            "job_id": "job-1",
            "item_id": "item-1",
            "level": "WARNING",
            "message": "apply detail",
            "file_path": "/imports/item.cbr",
            "extra": {"step": "apply"},
            "worker_id": 4,
            "duration_ms": 123,
        },
    ]


@pytest.mark.asyncio
async def test_persist_processed_item_result_returns_none_when_item_is_missing() -> None:
    calls: list[dict[str, Any]] = []
    executor = RecordingExecutor(ApplyResult())

    result = await persist_processed_item_result(
        FakeSession(job=_job(), item=None),
        job_id="job-1",
        item_id="item-1",
        file_path="/imports/item.cbr",
        processed=ProcessedItem(item_id="item-1", result=ItemResult.COMPLETED),
        payload_data={"file_path": "/imports/item.cbr"},
        executor=executor,
        config={},
        job_context=None,
        summary=JobRunSummary(),
        configured_level="INFO",
        persist_log=lambda _session, **kwargs: calls.append(kwargs),
        completed_at="2026-06-07T12:00:00+00:00",
    )

    assert result is None
    assert executor.calls == []
    assert calls == []


@pytest.mark.asyncio
async def test_persist_processed_item_failure_marks_item_and_updates_counters() -> None:
    calls: list[dict[str, Any]] = []
    job = _job()
    item = _item()
    session = FakeSession(job=job, item=item)
    summary = JobRunSummary(completed=2, failed=1, skipped=0, warnings=1)
    processed = ProcessedItem(
        item_id="item-1",
        result=ItemResult.COMPLETED,
        warning_message="original warning",
        duration_ms=123,
        worker_id=4,
    )

    def persist_log(active_session: object, **kwargs: Any) -> None:
        assert active_session is session
        calls.append(kwargs)

    result = await persist_processed_item_failure(
        session,
        job_id="job-1",
        item_id="item-1",
        file_path="/imports/item.cbr",
        processed=processed,
        persist_error=RuntimeError("database unavailable"),
        summary=summary,
        configured_level="INFO",
        persist_log=persist_log,
        completed_at="2026-06-07T12:30:00+00:00",
    )

    assert result is not None
    assert result.next_failed == 2
    assert result.failure_warnings == 2
    assert item.state == "FAILED"
    assert item.error_message == "Result persistence failed: database unavailable"
    assert item.warning_message == "original warning"
    assert item.worker_id == 4
    assert item.completed_at == "2026-06-07T12:30:00+00:00"
    assert job.completed_items == 2
    assert job.failed_items == 2
    assert job.skipped_items == 0
    assert job.warning_count == 2
    assert calls == [
        {
            "configured_level": "INFO",
            "job_id": "job-1",
            "item_id": "item-1",
            "level": "ERROR",
            "message": "Job result could not be persisted cleanly: database unavailable",
            "file_path": "/imports/item.cbr",
            "extra": {"original_result": "completed"},
            "worker_id": 4,
            "duration_ms": 123,
        }
    ]


@pytest.mark.asyncio
async def test_persist_processed_item_failure_returns_none_when_item_is_missing() -> None:
    calls: list[dict[str, Any]] = []

    result = await persist_processed_item_failure(
        FakeSession(job=_job(), item=None),
        job_id="job-1",
        item_id="item-1",
        file_path="/imports/item.cbr",
        processed=ProcessedItem(item_id="item-1", result=ItemResult.COMPLETED),
        persist_error=RuntimeError("boom"),
        summary=JobRunSummary(),
        configured_level="INFO",
        persist_log=lambda _session, **kwargs: calls.append(kwargs),
        completed_at="2026-06-07T12:30:00+00:00",
    )

    assert result is None
    assert calls == []


def test_persist_post_commit_logs_applies_item_context() -> None:
    calls: list[dict[str, Any]] = []
    session = object()
    processed = ProcessedItem(
        item_id="item-1",
        result=ItemResult.COMPLETED,
        duration_ms=456,
        worker_id=7,
    )

    def persist_log(active_session: object, **kwargs: Any) -> None:
        assert active_session is session
        calls.append(kwargs)

    persist_post_commit_logs(
        session,
        runtime_logs=[
            RuntimeLogEntry(level="INFO", message="post detail", extra={"step": "post"}),
            RuntimeLogEntry(
                level="WARNING",
                message="override path",
                file_path="/override/item.cbz",
            ),
        ],
        persist_log=persist_log,
        configured_level="INFO",
        job_id="job-1",
        item_id="item-1",
        file_path="/imports/item.cbr",
        processed=processed,
    )

    assert calls == [
        {
            "configured_level": "INFO",
            "job_id": "job-1",
            "item_id": "item-1",
            "level": "INFO",
            "message": "post detail",
            "file_path": "/imports/item.cbr",
            "extra": {"step": "post"},
            "worker_id": 7,
            "duration_ms": 456,
        },
        {
            "configured_level": "INFO",
            "job_id": "job-1",
            "item_id": "item-1",
            "level": "WARNING",
            "message": "override path",
            "file_path": "/override/item.cbz",
            "extra": {},
            "worker_id": 7,
            "duration_ms": 456,
        },
    ]
