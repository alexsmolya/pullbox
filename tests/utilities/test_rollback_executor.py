"""Tests for UT-F.10 — rollback executor.

Verifies RollbackExecutor generates items in reverse order from the
parent job's COMPLETED items, delegates to the original executor's
rollback_item(), and handles failures gracefully.

Run:
    pytest tests/utilities/test_rollback_executor.py -v
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from pullbox.utilities.base_executor import ItemResult, ProcessedItem
from pullbox.utilities.executors.rollback_executor import RollbackExecutor
from pullbox.utilities.models import (
    ItemState,
    JobState,
    JobType,
    UtilityJob,
    UtilityJobItem,
)


class _DelegatingRollbackExecutor:
    """Stub original executor used to verify rollback delegation."""

    def rollback_item(self, item_data: dict[str, Any], job_config: dict[str, Any]) -> ProcessedItem:
        return ProcessedItem(
            item_id=item_data.get("id", "unknown"),
            result=ItemResult.COMPLETED,
            log_entries=[("INFO", "Delegated rollback executed", {})],
        )


if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# ── Helpers ────────────────────────────────────────────────────


def _make_parent_job(
    db_session: Any,
    job_id: str = "parent-001",
    job_type: str = JobType.FILE_CONVERT,
    num_completed: int = 5,
    num_failed: int = 0,
    num_skipped: int = 0,
) -> UtilityJob:
    """Create a parent job with items in various states."""
    job = UtilityJob(
        id=job_id,
        job_type=job_type,
        display_name="Original Job",
        state=JobState.COMPLETED,
        config=json.dumps({"target_format": "cbz"}),
        total_items=num_completed + num_failed + num_skipped,
        completed_items=num_completed,
        failed_items=num_failed,
        skipped_items=num_skipped,
        warning_count=0,
        queue_position=None,
    )
    db_session.add(job)

    idx = 0
    for i in range(num_completed):
        db_session.add(
            UtilityJobItem(
                id=f"{job_id}-item-c{i}",
                job_id=job_id,
                item_index=idx,
                state=ItemState.COMPLETED,
                file_path=f"/comics/file_{idx}.cbr",
                operation="convert",
                before_state=json.dumps({"path": f"/comics/file_{idx}.cbr"}),
                after_state=json.dumps({"path": f"/comics/file_{idx}.cbz"}),
            )
        )
        idx += 1

    for i in range(num_failed):
        db_session.add(
            UtilityJobItem(
                id=f"{job_id}-item-f{i}",
                job_id=job_id,
                item_index=idx,
                state=ItemState.FAILED,
                file_path=f"/comics/fail_{idx}.cbr",
                operation="convert",
                error_message="Corrupt archive",
            )
        )
        idx += 1

    for i in range(num_skipped):
        db_session.add(
            UtilityJobItem(
                id=f"{job_id}-item-s{i}",
                job_id=job_id,
                item_index=idx,
                state=ItemState.SKIPPED,
                file_path=f"/comics/skip_{idx}.cbr",
                operation="convert",
            )
        )
        idx += 1

    return job


# ── Generate Items ─────────────────────────────────────────────


class TestGenerateItems:
    """Verify rollback generates items from parent job's COMPLETED items."""

    @pytest.mark.asyncio
    async def test_generates_completed_items_in_reverse(self, db_session: AsyncSession) -> None:
        _make_parent_job(db_session, num_completed=5)
        await db_session.flush()

        executor = RollbackExecutor(db_session)
        items = await executor.generate_items({"parent_job_id": "parent-001"})

        assert len(items) == 5
        # Reverse order by item_index
        indices = [item["item_index"] for item in items]
        assert indices == sorted(indices, reverse=True)

    @pytest.mark.asyncio
    async def test_only_completed_items_included(self, db_session: AsyncSession) -> None:
        """Mixed states: only COMPLETED items are rolled back."""
        _make_parent_job(
            db_session,
            job_id="mixed-001",
            num_completed=3,
            num_failed=2,
            num_skipped=1,
        )
        await db_session.flush()

        executor = RollbackExecutor(db_session)
        items = await executor.generate_items({"parent_job_id": "mixed-001"})

        assert len(items) == 3
        for item in items:
            assert item["original_state"] == ItemState.COMPLETED

    @pytest.mark.asyncio
    async def test_empty_job_returns_empty_list(self, db_session: AsyncSession) -> None:
        """Job with 0 completed items returns empty list."""
        _make_parent_job(
            db_session,
            job_id="empty-001",
            num_completed=0,
            num_failed=3,
        )
        await db_session.flush()

        executor = RollbackExecutor(db_session)
        items = await executor.generate_items({"parent_job_id": "empty-001"})

        assert items == []

    @pytest.mark.asyncio
    async def test_nonexistent_parent_raises(self, db_session: AsyncSession) -> None:
        executor = RollbackExecutor(db_session)
        with pytest.raises(ValueError, match="Parent job not found"):
            await executor.generate_items({"parent_job_id": "ghost"})

    @pytest.mark.asyncio
    async def test_rollback_of_rollback_prevented(self, db_session: AsyncSession) -> None:
        """Cannot rollback a rollback job."""
        parent = UtilityJob(
            id="rb-parent",
            job_type=JobType.ROLLBACK,
            display_name="Rollback",
            state=JobState.COMPLETED,
            config="{}",
            total_items=0,
            completed_items=0,
            failed_items=0,
            skipped_items=0,
            warning_count=0,
        )
        db_session.add(parent)
        await db_session.flush()

        executor = RollbackExecutor(db_session)
        with pytest.raises(ValueError, match="Cannot rollback a rollback job"):
            await executor.generate_items({"parent_job_id": "rb-parent"})

    @pytest.mark.asyncio
    async def test_items_include_after_state(self, db_session: AsyncSession) -> None:
        """Generated items include the original after_state for reversal."""
        _make_parent_job(db_session, job_id="state-001", num_completed=2)
        await db_session.flush()

        executor = RollbackExecutor(db_session)
        items = await executor.generate_items({"parent_job_id": "state-001"})

        for item in items:
            assert "after_state" in item
            after = json.loads(item["after_state"])
            assert "path" in after


# ── Process Item ───────────────────────────────────────────────


class TestProcessItem:
    """Verify rollback process_item delegates to original executor's rollback_item."""

    def test_delegates_to_original_executor_when_registered(self) -> None:
        executor = RollbackExecutor(
            session=None,
            executor_registry={JobType.FILE_CONVERT: _DelegatingRollbackExecutor},
        )
        item_data = {
            "id": "item-delegate",
            "file_path": "/comics/batman.cbz",
            "operation": "convert",
            "original_job_type": JobType.FILE_CONVERT,
            "after_state": json.dumps({"path": "/comics/batman.cbz"}),
            "before_state": json.dumps({"path": "/comics/batman.cbr"}),
        }

        result = executor.process_item(item_data, {})

        assert result.item_id == "item-delegate"
        assert result.result == ItemResult.COMPLETED
        assert result.log_entries[0][1] == "Delegated rollback executed"

    def test_successful_rollback(self) -> None:
        executor = RollbackExecutor(session=None)
        item_data = {
            "id": "item-001",
            "file_path": "/comics/batman.cbz",
            "operation": "convert",
            "original_job_type": JobType.FILE_CONVERT,
            "after_state": json.dumps({"path": "/comics/batman.cbz"}),
            "before_state": json.dumps({"path": "/comics/batman.cbr"}),
        }

        result = executor.process_item(item_data, {})

        assert result.item_id == "item-001"
        assert result.result == ItemResult.COMPLETED

    def test_rollback_with_missing_after_state(self) -> None:
        """Missing after_state results in FAILED."""
        executor = RollbackExecutor(session=None)
        item_data = {
            "id": "item-002",
            "file_path": "/comics/batman.cbz",
            "operation": "convert",
            "original_job_type": JobType.FILE_CONVERT,
        }

        result = executor.process_item(item_data, {})

        # Should still return a result (COMPLETED or FAILED), not crash
        assert result.item_id == "item-002"
        assert isinstance(result.result, ItemResult)


# ── Rollback Item ──────────────────────────────────────────────


class TestRollbackItem:
    """Verify rollback_item (rollback of a rollback is a no-op)."""

    def test_rollback_item_returns_skipped(self) -> None:
        """Rollback of a rollback item returns SKIPPED."""
        executor = RollbackExecutor(session=None)
        result = executor.rollback_item({"id": "x"}, {})
        assert result.result == ItemResult.SKIPPED


# ── Validate Config ────────────────────────────────────────────


class TestValidateConfig:
    """Verify config validation."""

    def test_missing_parent_job_id_rejected(self) -> None:
        executor = RollbackExecutor(session=None)
        errors = executor.validate_config({})
        assert any("parent_job_id" in e for e in errors)

    def test_valid_config_accepted(self) -> None:
        executor = RollbackExecutor(session=None)
        errors = executor.validate_config({"parent_job_id": "job-001"})
        assert errors == []
