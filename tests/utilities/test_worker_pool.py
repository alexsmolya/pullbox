"""Tests for UT-F.6 — worker pool manager.

Verifies WorkerPool dispatches batches via ProcessPoolExecutor,
assigns worker IDs, handles crashes gracefully, and supports shutdown.

Run:
    pytest tests/utilities/test_worker_pool.py -v
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from pullbox.utilities.base_executor import ExecutionMode, ItemResult, JobExecutor, ProcessedItem
from pullbox.utilities.worker_pool import WorkerPool

# ── Test Executors (must be module-level for pickling) ─────────


class SuccessExecutor(JobExecutor):
    """Executor that completes all items successfully."""

    async def generate_items(self, job_config: dict[str, Any]) -> list[dict[str, Any]]:
        return []

    def process_item(self, item_data: dict[str, Any], job_config: dict[str, Any]) -> ProcessedItem:
        return ProcessedItem(
            item_id=item_data["id"],
            result=ItemResult.COMPLETED,
            before_state={"path": item_data.get("file_path", "")},
            after_state={"processed": True},
            duration_ms=1,
            log_entries=[("INFO", f"Processed {item_data['id']}", {})],
        )

    def rollback_item(self, item_data: dict[str, Any], job_config: dict[str, Any]) -> ProcessedItem:
        return ProcessedItem(item_id=item_data["id"], result=ItemResult.COMPLETED)


class CrashingExecutor(JobExecutor):
    """Executor that raises on items with id 'crash'."""

    async def generate_items(self, job_config: dict[str, Any]) -> list[dict[str, Any]]:
        return []

    def process_item(self, item_data: dict[str, Any], job_config: dict[str, Any]) -> ProcessedItem:
        if item_data.get("id") == "crash":
            raise RuntimeError("Worker crashed!")
        return ProcessedItem(
            item_id=item_data["id"],
            result=ItemResult.COMPLETED,
        )

    def rollback_item(self, item_data: dict[str, Any], job_config: dict[str, Any]) -> ProcessedItem:
        return ProcessedItem(item_id=item_data["id"], result=ItemResult.COMPLETED)


class SlowExecutor(JobExecutor):
    """Executor with variable processing time based on item config."""

    async def generate_items(self, job_config: dict[str, Any]) -> list[dict[str, Any]]:
        return []

    def process_item(self, item_data: dict[str, Any], job_config: dict[str, Any]) -> ProcessedItem:
        delay = item_data.get("delay", 0)
        if delay:
            time.sleep(delay)
        return ProcessedItem(
            item_id=item_data["id"],
            result=ItemResult.COMPLETED,
            duration_ms=int(delay * 1000),
        )

    def rollback_item(self, item_data: dict[str, Any], job_config: dict[str, Any]) -> ProcessedItem:
        return ProcessedItem(item_id=item_data["id"], result=ItemResult.COMPLETED)


class NoneReturningExecutor(JobExecutor):
    """Executor that returns None instead of ProcessedItem."""

    async def generate_items(self, job_config: dict[str, Any]) -> list[dict[str, Any]]:
        return []

    def process_item(self, item_data: dict[str, Any], job_config: dict[str, Any]) -> ProcessedItem:
        return None  # type: ignore[return-value]

    def rollback_item(self, item_data: dict[str, Any], job_config: dict[str, Any]) -> ProcessedItem:
        return ProcessedItem(item_id=item_data["id"], result=ItemResult.COMPLETED)


# ── Basic Batch Processing ─────────────────────────────────────


class TestBatchProcessing:
    """Verify batch dispatch and result collection."""

    @pytest.mark.asyncio
    async def test_batch_of_five_items(self) -> None:
        pool = WorkerPool(max_workers=2)
        try:
            items = [{"id": f"item-{i}", "file_path": f"/comics/{i}.cbr"} for i in range(5)]
            results = await pool.process_batch(items, SuccessExecutor(), {})
            assert len(results) == 5
            assert all(r.result == ItemResult.COMPLETED for r in results)
        finally:
            pool.shutdown()

    @pytest.mark.asyncio
    async def test_empty_batch_returns_empty_list(self) -> None:
        pool = WorkerPool(max_workers=2)
        try:
            results = await pool.process_batch([], SuccessExecutor(), {})
            assert results == []
        finally:
            pool.shutdown()

    @pytest.mark.asyncio
    async def test_single_item_batch(self) -> None:
        pool = WorkerPool(max_workers=4)
        try:
            results = await pool.process_batch([{"id": "solo"}], SuccessExecutor(), {})
            assert len(results) == 1
            assert results[0].item_id == "solo"
        finally:
            pool.shutdown()

    @pytest.mark.asyncio
    async def test_more_items_than_workers(self) -> None:
        """20 items with 4 workers — all processed correctly."""
        pool = WorkerPool(max_workers=4)
        try:
            items = [{"id": f"item-{i}"} for i in range(20)]
            results = await pool.process_batch(items, SuccessExecutor(), {})
            assert len(results) == 20
            result_ids = {r.item_id for r in results}
            assert result_ids == {f"item-{i}" for i in range(20)}
        finally:
            pool.shutdown()

    @pytest.mark.asyncio
    async def test_fewer_items_than_workers(self) -> None:
        """2 items with 4 workers — no idle-worker errors."""
        pool = WorkerPool(max_workers=4)
        try:
            items = [{"id": "a"}, {"id": "b"}]
            results = await pool.process_batch(items, SuccessExecutor(), {})
            assert len(results) == 2
        finally:
            pool.shutdown()

    @pytest.mark.asyncio
    async def test_serial_execution_with_one_worker(self) -> None:
        """max_workers=1 effectively serial, still works."""
        pool = WorkerPool(max_workers=1)
        try:
            items = [{"id": f"item-{i}"} for i in range(5)]
            results = await pool.process_batch(items, SuccessExecutor(), {})
            assert len(results) == 5
        finally:
            pool.shutdown()


# ── Error Handling ─────────────────────────────────────────────


class TestErrorHandling:
    """Verify worker crashes are handled gracefully."""

    @pytest.mark.asyncio
    async def test_worker_crash_marks_item_failed(self) -> None:
        """Unhandled exception in worker → item FAILED, others still processed."""
        pool = WorkerPool(max_workers=2)
        try:
            items = [
                {"id": "ok-1"},
                {"id": "crash"},
                {"id": "ok-2"},
            ]
            results = await pool.process_batch(items, CrashingExecutor(), {})
            assert len(results) == 3
            by_id = {r.item_id: r for r in results}
            assert by_id["ok-1"].result == ItemResult.COMPLETED
            assert by_id["ok-2"].result == ItemResult.COMPLETED
            assert by_id["crash"].result == ItemResult.FAILED
            assert "Worker crashed" in (by_id["crash"].error_message or "")
        finally:
            pool.shutdown()

    @pytest.mark.asyncio
    async def test_none_return_handled_as_failed(self) -> None:
        """Worker returning None instead of ProcessedItem → FAILED."""
        pool = WorkerPool(max_workers=1)
        try:
            items = [{"id": "bad"}]
            results = await pool.process_batch(items, NoneReturningExecutor(), {})
            assert len(results) == 1
            assert results[0].result == ItemResult.FAILED
        finally:
            pool.shutdown()


# ── Worker ID Assignment ───────────────────────────────────────


class TestWorkerIdAssignment:
    """Verify worker IDs are assigned to results."""

    @pytest.mark.asyncio
    async def test_worker_ids_assigned(self) -> None:
        pool = WorkerPool(max_workers=2)
        try:
            items = [{"id": f"item-{i}"} for i in range(4)]
            results = await pool.process_batch(items, SuccessExecutor(), {})
            # Each result should have a worker_id assigned
            assert all(r.worker_id is not None for r in results)
        finally:
            pool.shutdown()


# ── Mixed Timing ───────────────────────────────────────────────


class TestMixedTiming:
    """Verify mix of fast and slow items."""

    @pytest.mark.asyncio
    async def test_fast_and_slow_items_all_collected(self) -> None:
        pool = WorkerPool(max_workers=2)
        try:
            items = [
                {"id": "fast-1", "delay": 0},
                {"id": "slow-1", "delay": 0.1},
                {"id": "fast-2", "delay": 0},
            ]
            results = await pool.process_batch(items, SlowExecutor(), {})
            assert len(results) == 3
            result_ids = {r.item_id for r in results}
            assert result_ids == {"fast-1", "slow-1", "fast-2"}
        finally:
            pool.shutdown()

    @pytest.mark.asyncio
    async def test_iter_batch_results_yields_before_slowest_item_finishes(self) -> None:
        pool = WorkerPool(execution_mode=ExecutionMode.THREAD, max_workers=2)
        try:
            items = [
                {"id": "fast-1", "delay": 0},
                {"id": "slow-1", "delay": 0.2},
            ]
            yielded_ids = [
                result.item_id
                async for result in pool.iter_batch_results(items, SlowExecutor(), {})
            ]

            assert yielded_ids[0] == "fast-1"
            assert set(yielded_ids) == {"fast-1", "slow-1"}
        finally:
            pool.shutdown()


# ── Shutdown ───────────────────────────────────────────────────


class TestShutdown:
    """Verify pool shutdown behavior."""

    @pytest.mark.asyncio
    async def test_shutdown_completes(self) -> None:
        pool = WorkerPool(max_workers=2)
        items = [{"id": "item-0"}]
        await pool.process_batch(items, SuccessExecutor(), {})
        pool.shutdown()
        # Should not hang or raise

    @pytest.mark.asyncio
    async def test_process_after_shutdown_raises(self) -> None:
        pool = WorkerPool(max_workers=2)
        pool.shutdown()
        with pytest.raises(RuntimeError, match="shut down"):
            await pool.process_batch([{"id": "x"}], SuccessExecutor(), {})

    @pytest.mark.asyncio
    async def test_sequential_batches_no_leak(self) -> None:
        """Rapid sequential batches don't cause resource leaks."""
        pool = WorkerPool(max_workers=2)
        try:
            for batch_num in range(5):
                items = [{"id": f"b{batch_num}-{i}"} for i in range(3)]
                results = await pool.process_batch(items, SuccessExecutor(), {})
                assert len(results) == 3
        finally:
            pool.shutdown()


# ── Large Batch ────────────────────────────────────────────────


class TestLargeBatch:
    """Verify large batch processing."""

    @pytest.mark.asyncio
    async def test_batch_of_100_items(self) -> None:
        """100 items with 4 workers completes without issues."""
        pool = WorkerPool(max_workers=4)
        try:
            items = [{"id": f"item-{i}"} for i in range(100)]
            results = await pool.process_batch(items, SuccessExecutor(), {})
            assert len(results) == 100
            assert all(r.result == ItemResult.COMPLETED for r in results)
        finally:
            pool.shutdown()
