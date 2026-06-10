"""Tests for utility job queue item helper functions."""

from __future__ import annotations

from pullbox.utilities.base_executor import ItemResult
from pullbox.utilities.job_queue_items import (
    build_batch_payloads,
    build_generated_job_items,
    item_result_to_state,
)
from pullbox.utilities.models import ItemState, UtilityJobItem


def test_item_result_to_state_maps_known_results_and_defaults_to_failed() -> None:
    assert item_result_to_state(ItemResult.COMPLETED) == ItemState.COMPLETED
    assert item_result_to_state(ItemResult.FAILED) == ItemState.FAILED
    assert item_result_to_state(ItemResult.SKIPPED) == ItemState.SKIPPED
    assert item_result_to_state("unexpected") == ItemState.FAILED


def test_build_batch_payloads_uses_before_state_when_available() -> None:
    item = UtilityJobItem(
        id="item-1",
        job_id="job-1",
        item_index=0,
        state=ItemState.PENDING,
        file_path="/imports/old.cbz",
        operation="rename",
        before_state='{"file_path": "/imports/new.cbz", "operation": "convert"}',
    )

    bundle = build_batch_payloads([item])

    assert bundle.payloads == [
        {
            "id": "item-1",
            "file_path": "/imports/new.cbz",
            "operation": "convert",
        }
    ]
    assert bundle.items_by_id == {"item-1": item}
    assert bundle.payloads_by_id == {"item-1": bundle.payloads[0]}


def test_build_batch_payloads_preserves_existing_blank_and_invalid_state_behavior() -> None:
    blank = UtilityJobItem(
        id="blank",
        job_id="job-1",
        item_index=0,
        state=ItemState.PENDING,
        file_path="/imports/blank.cbz",
        operation="convert",
        before_state="{}",
    )
    invalid = UtilityJobItem(
        id="invalid",
        job_id="job-1",
        item_index=1,
        state=ItemState.PENDING,
        file_path="/imports/invalid.cbz",
        operation="rename",
        before_state="{not-json",
    )

    bundle = build_batch_payloads([blank, invalid])

    assert bundle.payloads == [
        {
            "id": "blank",
            "file_path": "/imports/blank.cbz",
            "operation": "convert",
        },
        {
            "id": "invalid",
        },
    ]


def test_build_generated_job_items_preserves_payloads_and_defaults() -> None:
    item_ids = iter(["item-a", "item-b"])
    items = build_generated_job_items(
        job_id="job-1",
        items_data=[
            {"file_path": "/imports/a.cbz", "operation": "convert"},
            {"file_path": "/imports/b.cbz"},
        ],
        item_id_factory=lambda: next(item_ids),
    )

    assert [item.id for item in items] == ["item-a", "item-b"]
    assert [item.item_index for item in items] == [0, 1]
    assert [item.state for item in items] == [ItemState.PENDING, ItemState.PENDING]
    assert [item.file_path for item in items] == ["/imports/a.cbz", "/imports/b.cbz"]
    assert [item.operation for item in items] == ["convert", "unknown"]
    assert [item.before_state for item in items] == [
        '{"file_path": "/imports/a.cbz", "operation": "convert"}',
        '{"file_path": "/imports/b.cbz"}',
    ]
