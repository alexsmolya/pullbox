"""Helpers for utility batch-dispatch failure handling."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pullbox.utilities.base_executor import ItemResult, ProcessedItem
from pullbox.utilities.job_queue_processed_result import (
    apply_processed_item_snapshot,
    persist_processed_item_log_entries,
)
from pullbox.utilities.job_queue_runtime_state import apply_job_counter_snapshot
from pullbox.utilities.models import UtilityJob, UtilityJobItem

if TYPE_CHECKING:
    from collections.abc import Callable

    from pullbox.utilities.base_executor import JobRunSummary


def remaining_batch_item_ids(
    batch_payloads: list[dict[str, Any]],
    seen_item_ids: set[str],
) -> list[str]:
    """Return unprocessed payload IDs in their original batch order."""
    return [item_data["id"] for item_data in batch_payloads if item_data["id"] not in seen_item_ids]


def build_batch_dispatch_failure_item(item_id: str, exc: BaseException) -> ProcessedItem:
    """Build the synthetic failed result persisted for unprocessed batch items."""
    message = f"Batch dispatch failed: {exc}"
    return ProcessedItem(
        item_id=item_id,
        result=ItemResult.FAILED,
        error_message=message,
        duration_ms=0,
        log_entries=[("ERROR", message, {})],
    )


async def persist_batch_dispatch_failure_item(
    session: Any,
    *,
    job_id: str,
    item_id: str,
    file_path: str | None,
    processed: ProcessedItem,
    summary: JobRunSummary,
    configured_level: str,
    persist_log: Callable[..., None],
    completed_at: str,
) -> bool:
    """Persist one synthetic failed item after batch dispatch itself failed."""
    item = await session.get(UtilityJobItem, item_id)
    if item is None:
        return False

    apply_processed_item_snapshot(
        item,
        processed,
        completed_at=completed_at,
    )
    summary.failed += 1
    persist_processed_item_log_entries(
        session,
        processed=processed,
        persist_log=persist_log,
        configured_level=configured_level,
        job_id=job_id,
        item_id=item_id,
        file_path=file_path,
    )

    current_job = await session.get(UtilityJob, job_id)
    if current_job is not None:
        apply_job_counter_snapshot(
            current_job,
            completed=summary.completed,
            failed=summary.failed,
            skipped=summary.skipped,
            warnings=summary.warnings,
        )

    return True
