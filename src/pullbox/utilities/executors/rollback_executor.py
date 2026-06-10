"""Rollback executor — undoes completed items from a parent job.

Loads COMPLETED items from the original job in reverse order and
delegates to the original executor's rollback_item() method. Items
that fail to rollback are marked ROLLBACK_FAILED and processing
continues with remaining items.
"""

from __future__ import annotations

import json
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from pullbox.utilities.base_executor import (
    ApplyResult,
    ExecutionMode,
    FinalizeResult,
    ItemResult,
    JobExecutor,
    JobRunSummary,
    ProcessedItem,
)
from pullbox.utilities.logging_config import persist_runtime_utility_log
from pullbox.utilities.models import (
    ItemState,
    JobState,
    JobType,
    UtilityJob,
    UtilityJobItem,
)


class RollbackExecutor(JobExecutor):
    """Executor that undoes completed items by walking them in reverse.

    The rollback job's config must contain ``parent_job_id`` pointing to
    the original job whose COMPLETED items should be reversed.
    """

    execution_mode = ExecutionMode.SERIAL

    def __init__(
        self,
        session: Any | None = None,
        executor_registry: dict[str, type[JobExecutor]] | None = None,
    ) -> None:
        self._session = session
        self._executor_registry = executor_registry or {}

    def validate_config(self, job_config: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        if not job_config.get("parent_job_id"):
            errors.append("parent_job_id is required")
        return errors

    @asynccontextmanager
    async def _session_ctx(self) -> Any:
        if self._session is not None:
            yield self._session
            return

        from pullbox.database import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            yield session

    async def build_job_context(
        self,
        session: Any,
        job_config: dict[str, Any],
    ) -> dict[str, Any]:
        """Load COMPLETED items from parent job in reverse item_index order.

        Only COMPLETED items are included — FAILED and SKIPPED items
        are not rolled back.

        Raises:
            ValueError: If parent job not found or is itself a rollback job.
        """
        parent_id = job_config.get("parent_job_id", "")
        parent = await session.get(UtilityJob, parent_id)
        if parent is None:
            raise ValueError(f"Parent job not found: {parent_id}")

        if parent.job_type == JobType.ROLLBACK:
            raise ValueError("Cannot rollback a rollback job")

        result = await session.execute(
            select(UtilityJobItem)
            .where(
                UtilityJobItem.job_id == parent_id,
                UtilityJobItem.state == ItemState.COMPLETED,
            )
            .order_by(UtilityJobItem.item_index.desc())
        )
        completed_items = list(result.scalars().all())
        parent_config = json.loads(parent.config or "{}")

        items = [
            {
                "id": item.id,
                "file_path": item.file_path,
                "operation": f"rollback_{item.operation}",
                "item_index": item.item_index,
                "original_job_type": parent.job_type,
                "original_target": parent_config.get("target"),
                "original_state": item.state,
                "before_state": item.before_state or "{}",
                "after_state": item.after_state or "{}",
            }
            for item in completed_items
        ]
        return {
            "items": items,
            "parent_job_id": parent.id,
            "parent_job_type": parent.job_type,
        }

    async def generate_items(
        self,
        job_config: dict[str, Any],
        job_context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if job_context is None:
            async with self._session_ctx() as session:
                job_context = await self.build_job_context(session, job_config)
        return list((job_context or {}).get("items", []))

    def process_item(
        self,
        item_data: dict[str, Any],
        job_config: dict[str, Any],
        job_context: dict[str, Any] | None = None,
    ) -> ProcessedItem:
        """Reverse a single completed item.

        Currently performs a generic rollback (logging the reversal).
        Feature-specific executors will override rollback_item() with
        actual file operations (e.g., moving files back from trash).
        """
        start = time.monotonic()
        item_id = item_data.get("id", "unknown")

        try:
            original_job_type = str(item_data.get("original_job_type", "")).strip()
            executor_class = self._executor_registry.get(original_job_type)
            if executor_class is not None and original_job_type != JobType.ROLLBACK:
                original_executor = executor_class()
                rollback_runner = getattr(original_executor, "run_rollback_item", None)
                if rollback_runner is not None:
                    result: ProcessedItem = rollback_runner(item_data, job_config, None)
                    return result
                return original_executor.rollback_item(item_data, job_config)

            before_state_str = item_data.get("before_state", "{}")
            after_state_str = item_data.get("after_state", "{}")
            if isinstance(before_state_str, str):
                before_state = json.loads(before_state_str)
            else:
                before_state = before_state_str
            if isinstance(after_state_str, str):
                after_state = json.loads(after_state_str)
            else:
                after_state = after_state_str

            duration_ms = int((time.monotonic() - start) * 1000)

            return ProcessedItem(
                item_id=item_id,
                result=ItemResult.COMPLETED,
                before_state=after_state,
                after_state=before_state,
                duration_ms=duration_ms,
                log_entries=[
                    ("INFO", f"Rolled back item {item_id}", {}),
                ],
            )
        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            return ProcessedItem(
                item_id=item_id,
                result=ItemResult.FAILED,
                duration_ms=duration_ms,
                error_message=f"Rollback failed: {exc}",
                log_entries=[
                    ("ERROR", f"Rollback failed for {item_id}: {exc}", {}),
                ],
            )

    def rollback_item(
        self,
        item_data: dict[str, Any],
        job_config: dict[str, Any],
        job_context: dict[str, Any] | None = None,
    ) -> ProcessedItem:
        """Rollback of a rollback is a no-op — returns SKIPPED."""
        return ProcessedItem(
            item_id=item_data.get("id", "unknown"),
            result=ItemResult.SKIPPED,
            log_entries=[
                ("INFO", "Rollback of rollback skipped", {}),
            ],
        )

    async def apply_item_result(
        self,
        session: Any,
        item: Any,
        item_data: dict[str, Any],
        processed: ProcessedItem,
        job_config: dict[str, Any],
        job_context: dict[str, Any] | None,
        summary: JobRunSummary,
    ) -> ApplyResult:
        original_job_type = str(item_data.get("original_job_type", "") or "")
        executor_class = self._executor_registry.get(original_job_type)
        if executor_class is None:
            return ApplyResult()

        original_executor = executor_class()
        apply_rollback = getattr(original_executor, "apply_rollback_result", None)
        if apply_rollback is None:
            return ApplyResult()
        result: ApplyResult = await apply_rollback(session, item_data, processed)
        return result

    async def finalize_job(
        self,
        session: Any,
        job: Any,
        summary: JobRunSummary,
        job_config: dict[str, Any],
        job_context: dict[str, Any] | None,
    ) -> FinalizeResult:
        if not job.parent_job_id:
            return FinalizeResult()

        parent_job = await session.get(UtilityJob, job.parent_job_id)
        if parent_job is None:
            return FinalizeResult()

        configured_level = str(summary.metadata.get("utility_log_level", "INFO"))
        if JobState(job.state) == JobState.COMPLETED:
            parent_job.state = JobState.ROLLING_BACK
            parent_job.state = JobState.ROLLED_BACK
            parent_job.completed_at = datetime.now(UTC).isoformat()
            persist_runtime_utility_log(
                session,
                configured_level=configured_level,
                job_id=parent_job.id,
                level="INFO",
                message=f"Rollback completed via job {job.id}.",
                extra={"rollback_job_id": job.id},
            )
            return FinalizeResult()

        persist_runtime_utility_log(
            session,
            configured_level=configured_level,
            job_id=parent_job.id,
            level="ERROR",
            message=f"Rollback failed via job {job.id}.",
            extra={"rollback_job_id": job.id},
        )
        return FinalizeResult(
            error_message=(
                f"Rollback failed. {summary.completed} items rolled back, {summary.failed} failed."
            )
        )
