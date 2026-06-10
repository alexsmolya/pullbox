"""Tests for utility processed-result helper functions."""

from __future__ import annotations

import json

from pullbox.utilities.base_executor import ItemResult, ProcessedItem
from pullbox.utilities.job_queue_processed_result import (
    apply_processed_item_snapshot,
    build_processed_item_counter_delta,
    persist_processed_item_log_entries,
    processed_log_level,
)
from pullbox.utilities.models import ItemState, UtilityJobItem


def _item() -> UtilityJobItem:
    return UtilityJobItem(
        id="item-1",
        job_id="job-1",
        item_index=0,
        state=ItemState.IN_PROGRESS,
        file_path="/imports/item.cbz",
        operation="test",
    )


def test_build_processed_item_counter_delta_maps_results_and_warnings() -> None:
    completed = ProcessedItem(
        item_id="item-1",
        result=ItemResult.COMPLETED,
        warning_message="careful",
    )
    failed = ProcessedItem(item_id="item-2", result=ItemResult.FAILED)
    skipped = ProcessedItem(item_id="item-3", result=ItemResult.SKIPPED)

    assert build_processed_item_counter_delta(completed, warning_increment=2) == (
        1,
        0,
        0,
        3,
    )
    assert build_processed_item_counter_delta(failed) == (0, 1, 0, 0)
    assert build_processed_item_counter_delta(skipped) == (0, 0, 1, 0)


def test_apply_processed_item_snapshot_copies_success_fields() -> None:
    item = _item()
    processed = ProcessedItem(
        item_id="item-1",
        result=ItemResult.COMPLETED,
        before_state={"source": "/imports/item.cbz"},
        after_state={"target": "/comics/item.cbz"},
        duration_ms=123,
        error_message=None,
        warning_message="warning",
        worker_id=4,
    )

    apply_processed_item_snapshot(
        item,
        processed,
        completed_at="2026-06-07T12:00:00+00:00",
    )

    assert item.state == ItemState.COMPLETED
    assert item.duration_ms == 123
    assert item.error_message is None
    assert item.warning_message == "warning"
    assert item.worker_id == 4
    assert item.completed_at == "2026-06-07T12:00:00+00:00"
    assert json.loads(item.before_state) == {"source": "/imports/item.cbz"}
    assert json.loads(item.after_state) == {"target": "/comics/item.cbz"}


def test_apply_processed_item_snapshot_allows_failure_override() -> None:
    item = _item()
    processed = ProcessedItem(
        item_id="item-1",
        result=ItemResult.COMPLETED,
        duration_ms=15,
        warning_message="original warning",
        worker_id=2,
    )

    apply_processed_item_snapshot(
        item,
        processed,
        state=ItemState.FAILED,
        error_message="Result persistence failed: boom",
        completed_at="2026-06-07T12:30:00+00:00",
    )

    assert item.state == ItemState.FAILED
    assert item.error_message == "Result persistence failed: boom"
    assert item.warning_message == "original warning"
    assert item.worker_id == 2
    assert item.completed_at == "2026-06-07T12:30:00+00:00"


def test_processed_log_level_promotes_failed_items_to_error() -> None:
    failed = ProcessedItem(item_id="item-1", result=ItemResult.FAILED)
    completed = ProcessedItem(item_id="item-2", result=ItemResult.COMPLETED)

    assert processed_log_level(failed, "info") == "ERROR"
    assert processed_log_level(failed, None) == "ERROR"
    assert processed_log_level(completed, "warning") == "WARNING"
    assert processed_log_level(completed, None) == "INFO"


def test_persist_processed_item_log_entries_applies_queue_context() -> None:
    calls: list[dict[str, object]] = []
    session = object()
    processed = ProcessedItem(
        item_id="item-1",
        result=ItemResult.FAILED,
        duration_ms=123,
        worker_id=4,
        log_entries=[
            ("info", "worker detail", {"step": "convert"}),
            (None, "worker fallback", {}),
        ],
    )

    def persist_log(active_session: object, **kwargs: object) -> None:
        assert active_session is session
        calls.append(kwargs)

    persist_processed_item_log_entries(
        session,
        processed=processed,
        persist_log=persist_log,
        configured_level="INFO",
        job_id="job-1",
        item_id="db-item-1",
        file_path="/imports/item.cbr",
    )

    assert calls == [
        {
            "configured_level": "INFO",
            "job_id": "job-1",
            "item_id": "db-item-1",
            "level": "ERROR",
            "message": "worker detail",
            "file_path": "/imports/item.cbr",
            "extra": {"step": "convert"},
            "worker_id": 4,
            "duration_ms": 123,
        },
        {
            "configured_level": "INFO",
            "job_id": "job-1",
            "item_id": "db-item-1",
            "level": "ERROR",
            "message": "worker fallback",
            "file_path": "/imports/item.cbr",
            "extra": {},
            "worker_id": 4,
            "duration_ms": 123,
        },
    ]
