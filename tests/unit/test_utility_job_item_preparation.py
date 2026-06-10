"""Tests for utility dispatch item-preparation helpers."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from pullbox.utilities.base_executor import ItemResult, JobExecutor, ProcessedItem
from pullbox.utilities.job_queue_item_preparation import (
    mark_item_generation_failed,
    prepare_dispatch_items,
)
from pullbox.utilities.models import ItemState, JobState, JobType, UtilityJob, UtilityJobItem


class RecordingExecutor(JobExecutor):
    """Executor double that records context and item-generation calls."""

    def __init__(self) -> None:
        self.context_calls = 0
        self.generate_calls = 0

    async def build_job_context(
        self,
        session: Any,
        job_config: dict[str, Any],
    ) -> dict[str, Any]:
        self.context_calls += 1
        return {"configured_count": job_config.get("count")}

    async def generate_items(
        self,
        job_config: dict[str, Any],
        job_context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        self.generate_calls += 1
        count = int(job_config.get("count", 1))
        return [
            {
                "file_path": f"/imports/file-{idx}.cbz",
                "operation": "prepare",
                "context_count": job_context["configured_count"] if job_context else None,
            }
            for idx in range(count)
        ]

    def process_item(self, item_data: dict[str, Any], job_config: dict[str, Any]) -> ProcessedItem:
        return ProcessedItem(item_id=item_data.get("id", ""), result=ItemResult.COMPLETED)

    def rollback_item(self, item_data: dict[str, Any], job_config: dict[str, Any]) -> ProcessedItem:
        return ProcessedItem(item_id=item_data.get("id", ""), result=ItemResult.COMPLETED)


def _job(job_id: str = "job-1") -> UtilityJob:
    return UtilityJob(
        id=job_id,
        job_type=JobType.FILE_CONVERT,
        display_name="Convert",
        state=JobState.RUNNING,
        config="{}",
        total_items=0,
        completed_items=0,
        failed_items=0,
        skipped_items=0,
        warning_count=0,
    )


@pytest.mark.asyncio
async def test_prepare_dispatch_items_generates_rows_once(async_engine) -> None:  # type: ignore[no-untyped-def]
    session_factory = async_sessionmaker(async_engine, expire_on_commit=False)
    async with session_factory() as session:
        session.add(_job())
        await session.commit()
    executor = RecordingExecutor()

    prepared = await prepare_dispatch_items(
        session_factory,
        job_id="job-1",
        executor=executor,
        config={"count": 2},
    )

    assert prepared is not None
    assert prepared.job_context == {"configured_count": 2}
    assert executor.context_calls == 1
    assert executor.generate_calls == 1
    assert [item.item_index for item in prepared.pending_items] == [0, 1]
    assert [item.state for item in prepared.pending_items] == [
        ItemState.PENDING,
        ItemState.PENDING,
    ]
    assert [item.file_path for item in prepared.pending_items] == [
        "/imports/file-0.cbz",
        "/imports/file-1.cbz",
    ]

    async with session_factory() as session:
        job = await session.get(UtilityJob, "job-1")
        assert job is not None
        assert job.total_items == 2


@pytest.mark.asyncio
async def test_prepare_dispatch_items_reuses_existing_pending_rows(async_engine) -> None:  # type: ignore[no-untyped-def]
    session_factory = async_sessionmaker(async_engine, expire_on_commit=False)
    async with session_factory() as session:
        session.add(_job())
        session.add(
            UtilityJobItem(
                id="existing-item",
                job_id="job-1",
                item_index=0,
                state=ItemState.PENDING,
                file_path="/imports/existing.cbz",
                operation="resume",
                before_state='{"file_path": "/imports/existing.cbz"}',
            )
        )
        await session.commit()
    executor = RecordingExecutor()

    prepared = await prepare_dispatch_items(
        session_factory,
        job_id="job-1",
        executor=executor,
        config={"count": 2},
    )

    assert prepared is not None
    assert prepared.job_context == {"configured_count": 2}
    assert executor.context_calls == 1
    assert executor.generate_calls == 0
    assert [item.id for item in prepared.pending_items] == ["existing-item"]

    async with session_factory() as session:
        result = await session.execute(select(UtilityJobItem))
        assert len(result.scalars().all()) == 1


@pytest.mark.asyncio
async def test_mark_item_generation_failed_transitions_job_to_failed(db_session) -> None:  # type: ignore[no-untyped-def]
    job = _job()
    db_session.add(job)
    await db_session.flush()

    marked = await mark_item_generation_failed(
        db_session,
        job_id="job-1",
        exc=RuntimeError("Cannot discover items"),
    )
    await db_session.refresh(job)

    assert marked is True
    assert job.state == JobState.FAILED
    assert job.error_message == "Item generation failed: Cannot discover items"
    assert job.completed_at is not None


@pytest.mark.asyncio
async def test_mark_item_generation_failed_returns_false_when_job_missing(db_session) -> None:  # type: ignore[no-untyped-def]
    marked = await mark_item_generation_failed(
        db_session,
        job_id="missing",
        exc=RuntimeError("Cannot discover items"),
    )

    assert marked is False
