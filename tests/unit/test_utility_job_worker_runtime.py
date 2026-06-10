"""Tests for utility job worker-runtime helpers."""

from __future__ import annotations

from typing import Any

import pytest

from pullbox.utilities.base_executor import ExecutionMode, ItemResult, ProcessedItem
from pullbox.utilities.job_queue_worker_runtime import (
    build_processed_item_stream,
    build_worker_runtime,
)
from pullbox.utilities.models import JobType


class ModeExecutor:
    def __init__(self, mode: ExecutionMode) -> None:
        self.mode = mode

    def get_execution_mode(
        self,
        job_config: dict[str, Any],
        job_context: dict[str, Any] | None = None,
    ) -> ExecutionMode:
        return self.mode


class ModernWorkerPool:
    def __init__(self, *, execution_mode: ExecutionMode, max_workers: int) -> None:
        self.execution_mode = execution_mode
        self.max_workers = max_workers


class LegacyWorkerPool:
    def __init__(self, *, max_workers: int) -> None:
        self.max_workers = max_workers


class StreamExecutor(ModeExecutor):
    def __init__(self) -> None:
        super().__init__(ExecutionMode.SERIAL)
        self.processed_payloads: list[dict[str, Any]] = []

    def process_item(
        self,
        item_data: dict[str, Any],
        job_config: dict[str, Any],
    ) -> ProcessedItem:
        self.processed_payloads.append(item_data)
        return ProcessedItem(
            item_id=str(item_data["id"]),
            result=ItemResult.COMPLETED,
        )


def test_build_worker_runtime_uses_serial_batch_size_and_modern_pool() -> None:
    runtime = build_worker_runtime(
        executor=ModeExecutor(ExecutionMode.SERIAL),
        config={},
        job_context=None,
        worker_count=4,
        worker_pool_factory=ModernWorkerPool,
    )

    assert runtime.execution_mode == ExecutionMode.SERIAL
    assert runtime.batch_size == 1
    assert runtime.worker_pool.execution_mode == ExecutionMode.SERIAL
    assert runtime.worker_pool.max_workers == 4


def test_build_worker_runtime_uses_worker_count_for_parallel_batches() -> None:
    runtime = build_worker_runtime(
        executor=ModeExecutor(ExecutionMode.THREAD),
        config={},
        job_context={"ready": True},
        worker_count=3,
        worker_pool_factory=ModernWorkerPool,
    )

    assert runtime.execution_mode == ExecutionMode.THREAD
    assert runtime.batch_size == 3
    assert runtime.worker_pool.execution_mode == ExecutionMode.THREAD
    assert runtime.worker_pool.max_workers == 3


def test_build_worker_runtime_preserves_legacy_worker_pool_fallback() -> None:
    runtime = build_worker_runtime(
        executor=ModeExecutor(ExecutionMode.PROCESS),
        config={},
        job_context=None,
        worker_count=2,
        worker_pool_factory=LegacyWorkerPool,
    )

    assert runtime.execution_mode == ExecutionMode.PROCESS
    assert runtime.batch_size == 2
    assert runtime.worker_pool.max_workers == 2


@pytest.mark.asyncio
async def test_build_processed_item_stream_runs_rollback_items_inline() -> None:
    executor = StreamExecutor()
    payloads = [{"id": "item-1"}]

    processed = [
        item
        async for item in build_processed_item_stream(
            job_type=JobType.ROLLBACK,
            worker_pool=object(),
            payloads=payloads,
            executor=executor,
            config={"target": "rollback"},
            job_context={"ignored": True},
        )
    ]

    assert executor.processed_payloads == payloads
    assert [item.item_id for item in processed] == ["item-1"]
    assert processed[0].worker_id == 1


@pytest.mark.asyncio
async def test_build_processed_item_stream_uses_modern_worker_pool() -> None:
    class RecordingPool:
        def __init__(self) -> None:
            self.calls: list[tuple[Any, ...]] = []

        async def iter_batch_results(
            self,
            payloads: list[dict[str, Any]],
            executor: Any,
            config: dict[str, Any],
            job_context: dict[str, Any] | None,
        ) -> Any:
            self.calls.append((payloads, executor, config, job_context))
            yield ProcessedItem(item_id="item-1", result=ItemResult.COMPLETED)

    pool = RecordingPool()
    executor = StreamExecutor()
    payloads = [{"id": "item-1"}]
    config = {"target": "cbz"}
    job_context = {"ready": True}

    processed = [
        item
        async for item in build_processed_item_stream(
            job_type=JobType.FILE_CONVERT,
            worker_pool=pool,
            payloads=payloads,
            executor=executor,
            config=config,
            job_context=job_context,
        )
    ]

    assert [item.item_id for item in processed] == ["item-1"]
    assert pool.calls == [(payloads, executor, config, job_context)]


@pytest.mark.asyncio
async def test_build_processed_item_stream_preserves_legacy_worker_pool_fallback() -> None:
    class LegacyStreamPool:
        def __init__(self) -> None:
            self.calls: list[tuple[Any, ...]] = []

        async def iter_batch_results(
            self,
            payloads: list[dict[str, Any]],
            executor: Any,
            config: dict[str, Any],
        ) -> Any:
            self.calls.append((payloads, executor, config))
            yield ProcessedItem(item_id="item-1", result=ItemResult.COMPLETED)

    pool = LegacyStreamPool()
    executor = StreamExecutor()
    payloads = [{"id": "item-1"}]
    config = {"target": "cbz"}

    processed = [
        item
        async for item in build_processed_item_stream(
            job_type=JobType.FILE_CONVERT,
            worker_pool=pool,
            payloads=payloads,
            executor=executor,
            config=config,
            job_context={"unsupported": True},
        )
    ]

    assert [item.item_id for item in processed] == ["item-1"]
    assert pool.calls == [(payloads, executor, config)]
