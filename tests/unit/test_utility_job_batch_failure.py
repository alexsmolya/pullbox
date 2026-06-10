"""Tests for utility batch-dispatch failure helpers."""

from __future__ import annotations

from typing import Any

import pytest

from pullbox.utilities.base_executor import ItemResult, JobRunSummary
from pullbox.utilities.job_queue_batch_failure import (
    build_batch_dispatch_failure_item,
    persist_batch_dispatch_failure_item,
    remaining_batch_item_ids,
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


def _job() -> UtilityJob:
    return UtilityJob(
        id="job-1",
        job_type=JobType.FILE_CONVERT,
        display_name="Convert",
        state=JobState.RUNNING,
        config="{}",
        total_items=3,
        completed_items=1,
        failed_items=2,
        skipped_items=0,
        warning_count=0,
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


def test_remaining_batch_item_ids_preserves_payload_order() -> None:
    payloads = [{"id": "first"}, {"id": "second"}, {"id": "third"}]

    assert remaining_batch_item_ids(payloads, {"second"}) == ["first", "third"]


def test_build_batch_dispatch_failure_item_uses_actionable_error() -> None:
    processed = build_batch_dispatch_failure_item("item-1", RuntimeError("boom"))

    assert processed.item_id == "item-1"
    assert processed.result == ItemResult.FAILED
    assert processed.error_message == "Batch dispatch failed: boom"
    assert processed.duration_ms == 0
    assert processed.log_entries == [("ERROR", "Batch dispatch failed: boom", {})]


@pytest.mark.asyncio
async def test_persist_batch_dispatch_failure_item_marks_item_and_updates_counters() -> None:
    calls: list[dict[str, Any]] = []
    job = _job()
    item = _item()
    session = FakeSession(job=job, item=item)
    summary = JobRunSummary(completed=1, failed=2, skipped=0, warnings=0)
    processed = build_batch_dispatch_failure_item("item-1", RuntimeError("worker boom"))

    def persist_log(active_session: object, **kwargs: Any) -> None:
        assert active_session is session
        calls.append(kwargs)

    persisted = await persist_batch_dispatch_failure_item(
        session,
        job_id="job-1",
        item_id="item-1",
        file_path="/imports/item.cbr",
        processed=processed,
        summary=summary,
        configured_level="INFO",
        persist_log=persist_log,
        completed_at="2026-06-07T12:00:00+00:00",
    )

    assert persisted is True
    assert summary.failed == 3
    assert item.state == "FAILED"
    assert item.error_message == "Batch dispatch failed: worker boom"
    assert item.completed_at == "2026-06-07T12:00:00+00:00"
    assert job.completed_items == 1
    assert job.failed_items == 3
    assert job.skipped_items == 0
    assert job.warning_count == 0
    assert calls == [
        {
            "configured_level": "INFO",
            "job_id": "job-1",
            "item_id": "item-1",
            "level": "ERROR",
            "message": "Batch dispatch failed: worker boom",
            "file_path": "/imports/item.cbr",
            "extra": {},
            "worker_id": None,
            "duration_ms": 0,
        }
    ]


@pytest.mark.asyncio
async def test_persist_batch_dispatch_failure_item_returns_false_when_item_is_missing() -> None:
    calls: list[dict[str, Any]] = []
    summary = JobRunSummary(completed=1, failed=2, skipped=0, warnings=0)
    processed = build_batch_dispatch_failure_item("item-1", RuntimeError("worker boom"))

    persisted = await persist_batch_dispatch_failure_item(
        FakeSession(job=_job(), item=None),
        job_id="job-1",
        item_id="item-1",
        file_path="/imports/item.cbr",
        processed=processed,
        summary=summary,
        configured_level="INFO",
        persist_log=lambda _session, **kwargs: calls.append(kwargs),
        completed_at="2026-06-07T12:00:00+00:00",
    )

    assert persisted is False
    assert summary.failed == 2
    assert calls == []
