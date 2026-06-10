"""Processed item persistence helpers for utility queue dispatch."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from pullbox.utilities.base_executor import ItemResult, ProcessedItem
from pullbox.utilities.job_queue_items import item_result_to_state

if TYPE_CHECKING:
    from collections.abc import Callable

    from pullbox.utilities.models import ItemState, UtilityJobItem


def build_processed_item_counter_delta(
    processed: ProcessedItem,
    *,
    warning_increment: int = 0,
) -> tuple[int, int, int, int]:
    """Return completed/failed/skipped/warning counter deltas for a processed item."""
    completed_delta = 0
    failed_delta = 0
    skipped_delta = 0
    warning_delta = warning_increment
    if processed.result == ItemResult.COMPLETED:
        completed_delta = 1
    elif processed.result == ItemResult.FAILED:
        failed_delta = 1
    elif processed.result == ItemResult.SKIPPED:
        skipped_delta = 1

    if processed.warning_message:
        warning_delta += 1

    return completed_delta, failed_delta, skipped_delta, warning_delta


def processed_log_level(processed: ProcessedItem, level: str | None) -> str:
    """Return the persisted log level for a worker log entry."""
    if processed.result == ItemResult.FAILED:
        return "ERROR"
    return str(level or "INFO").upper()


def persist_processed_item_log_entries(
    session: Any,
    *,
    processed: ProcessedItem,
    persist_log: Callable[..., None],
    configured_level: str,
    job_id: str,
    item_id: str,
    file_path: str | None,
) -> None:
    """Persist worker-emitted log entries with shared queue context."""
    for level, message, extra in processed.log_entries or []:
        persist_log(
            session,
            configured_level=configured_level,
            job_id=job_id,
            item_id=item_id,
            level=processed_log_level(processed, level),
            message=message,
            file_path=file_path,
            extra=extra,
            worker_id=processed.worker_id,
            duration_ms=processed.duration_ms,
        )


def apply_processed_item_snapshot(
    item: UtilityJobItem,
    processed: ProcessedItem,
    *,
    completed_at: str,
    state: ItemState | None = None,
    error_message: str | None = None,
) -> None:
    """Copy processed item fields onto a DB item row."""
    item.state = state or item_result_to_state(processed.result)
    item.duration_ms = processed.duration_ms
    item.error_message = error_message if error_message is not None else processed.error_message
    item.warning_message = processed.warning_message
    item.worker_id = processed.worker_id
    item.completed_at = completed_at

    if processed.before_state:
        item.before_state = json.dumps(processed.before_state)
    if processed.after_state:
        item.after_state = json.dumps(processed.after_state)
