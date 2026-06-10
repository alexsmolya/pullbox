"""Tests for utility job batch state helpers."""

from __future__ import annotations

from typing import Any

import pytest

from pullbox.utilities.base_executor import JobRunSummary
from pullbox.utilities.job_queue_batch_state import (
    lease_dispatch_batch,
    mark_batch_items_in_progress,
    prepare_batch_checkpoint,
)
from pullbox.utilities.models import ItemState, JobState, JobType, UtilityJob, UtilityJobItem


class FakeSession:
    def __init__(self, job: UtilityJob | None) -> None:
        self.job = job
        self.commit_count = 0

    async def get(self, model: type[Any], item_id: str) -> Any:
        assert model is UtilityJob
        assert item_id == "job-1"
        return self.job

    async def commit(self) -> None:
        self.commit_count += 1


def _job(state: JobState) -> UtilityJob:
    return UtilityJob(
        id="job-1",
        job_type=JobType.FILE_CONVERT,
        display_name="Convert",
        state=state,
        config="{}",
        total_items=1,
        completed_items=0,
        failed_items=0,
        skipped_items=0,
        warning_count=0,
    )


def _item(item_id: str, *, state: ItemState = ItemState.PENDING) -> UtilityJobItem:
    return UtilityJobItem(
        id=item_id,
        job_id="job-1",
        item_index=0,
        state=state,
        file_path=f"/imports/{item_id}.cbz",
        operation="test",
        completed_at="2026-06-07T12:00:00+00:00",
        worker_id=99,
    )


@pytest.mark.asyncio
async def test_mark_batch_items_in_progress_updates_only_selected_items(db_session) -> None:  # type: ignore[no-untyped-def]
    db_session.add(_job(JobState.RUNNING))
    first = _item("first")
    second = _item("second")
    untouched = _item("untouched")
    db_session.add_all([first, second, untouched])
    await db_session.flush()

    await mark_batch_items_in_progress(
        db_session,
        item_ids=["first", "second"],
        started_at="2026-06-07T12:30:00+00:00",
    )
    await db_session.refresh(first)
    await db_session.refresh(second)
    await db_session.refresh(untouched)

    assert first.state == ItemState.IN_PROGRESS
    assert first.started_at == "2026-06-07T12:30:00+00:00"
    assert first.completed_at is None
    assert first.worker_id is None
    assert second.state == ItemState.IN_PROGRESS
    assert untouched.state == ItemState.PENDING
    assert untouched.completed_at == "2026-06-07T12:00:00+00:00"
    assert untouched.worker_id == 99


@pytest.mark.asyncio
async def test_lease_dispatch_batch_marks_selected_slice_in_progress(db_session) -> None:  # type: ignore[no-untyped-def]
    db_session.add(_job(JobState.RUNNING))
    first = _item("first")
    second = _item("second")
    third = _item("third")
    db_session.add_all([first, second, third])
    await db_session.flush()

    batch_items = await lease_dispatch_batch(
        db_session,
        pending_items=[first, second, third],
        batch_start=1,
        batch_size=2,
        started_at="2026-06-07T13:00:00+00:00",
    )
    await db_session.refresh(first)
    await db_session.refresh(second)
    await db_session.refresh(third)

    assert [item.id for item in batch_items] == ["second", "third"]
    assert first.state == ItemState.PENDING
    assert second.state == ItemState.IN_PROGRESS
    assert second.started_at == "2026-06-07T13:00:00+00:00"
    assert third.state == ItemState.IN_PROGRESS


@pytest.mark.asyncio
async def test_prepare_batch_checkpoint_continues_running_job_and_refreshes_log_level() -> None:
    summary = JobRunSummary()
    session = FakeSession(_job(JobState.RUNNING))

    async def get_log_level(_session: object) -> str:
        return "WARNING"

    checkpoint = await prepare_batch_checkpoint(
        session,
        job_id="job-1",
        summary=summary,
        get_utility_log_level=get_log_level,
    )

    assert checkpoint.should_continue is True
    assert checkpoint.utility_log_level == "WARNING"
    assert summary.metadata["utility_log_level"] == "WARNING"
    assert session.commit_count == 0


@pytest.mark.asyncio
async def test_prepare_batch_checkpoint_pauses_pausing_job() -> None:
    job = _job(JobState.PAUSING)
    summary = JobRunSummary()
    session = FakeSession(job)

    async def get_log_level(_session: object) -> str:
        return "INFO"

    checkpoint = await prepare_batch_checkpoint(
        session,
        job_id="job-1",
        summary=summary,
        get_utility_log_level=get_log_level,
    )

    assert checkpoint.should_continue is False
    assert checkpoint.utility_log_level == "INFO"
    assert job.state == JobState.PAUSED
    assert session.commit_count == 1


@pytest.mark.asyncio
async def test_prepare_batch_checkpoint_stops_cancelling_job_without_commit() -> None:
    job = _job(JobState.CANCELLING)
    summary = JobRunSummary()
    session = FakeSession(job)

    async def get_log_level(_session: object) -> str:
        return "DEBUG"

    checkpoint = await prepare_batch_checkpoint(
        session,
        job_id="job-1",
        summary=summary,
        get_utility_log_level=get_log_level,
    )

    assert checkpoint.should_continue is False
    assert checkpoint.utility_log_level == "DEBUG"
    assert job.state == JobState.CANCELLING
    assert session.commit_count == 0
