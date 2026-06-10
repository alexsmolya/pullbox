"""Tests for UT-F.11 — foundation integration test.

Verifies the entire foundation stack works together: job creation,
state transitions, batch execution with WorkerPool, checkpointing,
startup recovery, and job controls (pause/resume/cancel/rollback).

Run:
    pytest tests/utilities/test_foundation_integration.py -v
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker  # noqa: TC002

from pullbox.utilities.base_executor import ItemResult
from pullbox.utilities.job_queue import JobQueueManager
from pullbox.utilities.models import (
    ItemState,
    JobState,
    JobType,
    UtilityJob,
    UtilityJobItem,
    UtilityJobLog,
)
from pullbox.utilities.worker_pool import WorkerPool

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# ── Helpers ────────────────────────────────────────────────────


def _make_manager(
    session_factory: async_sessionmaker[Any],
) -> JobQueueManager:
    """Create a JobQueueManager with StubExecutor registered."""
    from tests.utilities.conftest import StubExecutor

    mgr = JobQueueManager(session_factory=session_factory)
    mgr.register_executor(JobType.FILE_CONVERT, StubExecutor)
    return mgr


async def _run_job_to_completion(
    mgr: JobQueueManager,
    session: Any,
    job: UtilityJob,
) -> None:
    """Simulate the execution loop for a single job to completion.

    This mimics what the poll loop would do: transition to RUNNING,
    generate items, dispatch batches, checkpoint results.
    """
    from tests.utilities.conftest import StubExecutor

    executor = StubExecutor()

    # Transition to RUNNING
    mgr.transition(job, JobState.RUNNING)

    # Generate items
    config = json.loads(job.config)
    item_dicts = await executor.generate_items(config)

    # Create UtilityJobItem rows
    import os

    for idx, item_dict in enumerate(item_dicts):
        item_id = os.urandom(8).hex()
        item = UtilityJobItem(
            id=item_id,
            job_id=job.id,
            item_index=idx,
            state=ItemState.PENDING,
            file_path=item_dict.get("file_path"),
            operation=item_dict.get("operation", "test"),
        )
        session.add(item)
        item_dict["id"] = item_id

    job.total_items = len(item_dicts)
    await session.flush()

    # Process items via WorkerPool
    pool = WorkerPool(max_workers=2)
    try:
        results = await pool.process_batch(item_dicts, executor, config)

        # Checkpoint results
        for result in results:
            db_item = await session.get(UtilityJobItem, result.item_id)
            if db_item:
                if result.result == ItemResult.COMPLETED:
                    db_item.state = ItemState.COMPLETED
                    job.completed_items = (job.completed_items or 0) + 1
                elif result.result == ItemResult.FAILED:
                    db_item.state = ItemState.FAILED
                    job.failed_items = (job.failed_items or 0) + 1
                elif result.result == ItemResult.SKIPPED:
                    db_item.state = ItemState.SKIPPED
                    job.skipped_items = (job.skipped_items or 0) + 1
                db_item.duration_ms = result.duration_ms
                db_item.before_state = json.dumps(result.before_state)
                db_item.after_state = json.dumps(result.after_state)

            # Insert log entries
            for level, message, extra in result.log_entries:
                session.add(
                    UtilityJobLog(
                        job_id=job.id,
                        item_id=result.item_id,
                        level=level,
                        message=message,
                        extra=json.dumps(extra),
                    )
                )

        mgr.transition(job, JobState.COMPLETED)
        await session.flush()
    finally:
        pool.shutdown()


# ── Full Lifecycle ─────────────────────────────────────────────


class TestFullLifecycle:
    """Verify complete job lifecycle: submit → queue → run → complete."""

    @pytest.mark.asyncio
    async def test_submit_run_complete(
        self,
        db_session: AsyncSession,
        session_factory: async_sessionmaker[Any],
    ) -> None:
        mgr = _make_manager(session_factory)

        # Submit
        job = await mgr.create_job(
            session=db_session,
            job_type=JobType.FILE_CONVERT,
            display_name="Integration Test",
            config={"count": 5},
        )
        assert job.state == JobState.QUEUED

        # Run to completion
        await _run_job_to_completion(mgr, db_session, job)

        # Verify final state
        assert job.state == JobState.COMPLETED
        assert job.completed_items == 5
        assert job.total_items == 5
        assert job.completed_at is not None

        # Verify items
        result = await db_session.execute(
            select(UtilityJobItem).where(UtilityJobItem.job_id == job.id)
        )
        items = list(result.scalars().all())
        assert len(items) == 5
        assert all(i.state == ItemState.COMPLETED for i in items)

        # Verify logs were created
        result = await db_session.execute(
            select(UtilityJobLog).where(UtilityJobLog.job_id == job.id)
        )
        logs = list(result.scalars().all())
        assert len(logs) == 5

    @pytest.mark.asyncio
    async def test_single_item_job(
        self,
        db_session: AsyncSession,
        session_factory: async_sessionmaker[Any],
    ) -> None:
        """Job with exactly 1 item completes correctly."""
        mgr = _make_manager(session_factory)
        job = await mgr.create_job(
            session=db_session,
            job_type=JobType.FILE_CONVERT,
            display_name="Single Item",
            config={"count": 1},
        )

        await _run_job_to_completion(mgr, db_session, job)

        assert job.state == JobState.COMPLETED
        assert job.completed_items == 1
        assert job.total_items == 1

    @pytest.mark.asyncio
    async def test_zero_items_completes_immediately(
        self,
        db_session: AsyncSession,
        session_factory: async_sessionmaker[Any],
    ) -> None:
        """Job with 0 items transitions directly to COMPLETED."""
        mgr = _make_manager(session_factory)
        job = await mgr.create_job(
            session=db_session,
            job_type=JobType.FILE_CONVERT,
            display_name="Empty Job",
            config={"count": 0},
        )

        await _run_job_to_completion(mgr, db_session, job)

        assert job.state == JobState.COMPLETED
        assert job.total_items == 0


# ── Pause / Resume ─────────────────────────────────────────────


class TestPauseResume:
    """Verify pause and resume lifecycle."""

    @pytest.mark.asyncio
    async def test_pause_then_resume(
        self,
        db_session: AsyncSession,
        session_factory: async_sessionmaker[Any],
    ) -> None:
        mgr = _make_manager(session_factory)
        job = await mgr.create_job(
            session=db_session,
            job_type=JobType.FILE_CONVERT,
            display_name="Pause Test",
            config={"count": 3},
        )

        # Transition to running, then pause
        mgr.transition(job, JobState.RUNNING)
        mgr.transition(job, JobState.PAUSING)
        mgr.transition(job, JobState.PAUSED)
        assert job.state == JobState.PAUSED
        assert job.paused_at is not None

        # Resume
        await mgr.resume_job(db_session, job.id)
        assert job.state == JobState.QUEUED
        assert job.queue_position == 0


# ── Cancel ─────────────────────────────────────────────────────


class TestCancel:
    """Verify cancel lifecycle."""

    @pytest.mark.asyncio
    async def test_cancel_running_job(
        self,
        db_session: AsyncSession,
        session_factory: async_sessionmaker[Any],
    ) -> None:
        mgr = _make_manager(session_factory)
        job = await mgr.create_job(
            session=db_session,
            job_type=JobType.FILE_CONVERT,
            display_name="Cancel Test",
            config={"count": 5},
        )

        mgr.transition(job, JobState.RUNNING)
        await mgr.cancel_job(db_session, job.id)
        assert job.state == JobState.CANCELLING

        # Simulate execution loop finishing
        mgr.transition(job, JobState.CANCELLED)
        assert job.state == JobState.CANCELLED
        assert job.completed_at is not None

    @pytest.mark.asyncio
    async def test_cancel_queued_job(
        self,
        db_session: AsyncSession,
        session_factory: async_sessionmaker[Any],
    ) -> None:
        """Cancelling a QUEUED job goes directly to CANCELLED."""
        mgr = _make_manager(session_factory)
        job = await mgr.create_job(
            session=db_session,
            job_type=JobType.FILE_CONVERT,
            display_name="Cancel Queued",
            config={},
        )

        await mgr.cancel_job(db_session, job.id)
        assert job.state == JobState.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_with_rollback(
        self,
        db_session: AsyncSession,
        session_factory: async_sessionmaker[Any],
    ) -> None:
        """Cancel with rollback=True creates a rollback job."""
        mgr = _make_manager(session_factory)
        job = await mgr.create_job(
            session=db_session,
            job_type=JobType.FILE_CONVERT,
            display_name="Rollback Test",
            config={},
        )

        mgr.transition(job, JobState.RUNNING)
        await mgr.cancel_job(db_session, job.id, rollback=True)

        # Original job is cancelling
        assert job.state == JobState.CANCELLING

        # Rollback job was created
        result = await db_session.execute(
            select(UtilityJob).where(UtilityJob.job_type == JobType.ROLLBACK)
        )
        rollback_job = result.scalar_one()
        assert rollback_job.parent_job_id == job.id
        assert rollback_job.state == JobState.QUEUED


# ── Startup Recovery ───────────────────────────────────────────


class TestStartupRecovery:
    """Verify startup recovery transitions interrupted jobs."""

    @pytest.mark.asyncio
    async def test_recovery_transitions_running_to_paused(
        self,
        db_session: AsyncSession,
        session_factory: async_sessionmaker[Any],
    ) -> None:
        mgr = _make_manager(session_factory)
        job = await mgr.create_job(
            session=db_session,
            job_type=JobType.FILE_CONVERT,
            display_name="Interrupted",
            config={"count": 10},
        )

        # Simulate crash mid-execution
        mgr.transition(job, JobState.RUNNING)
        await db_session.flush()

        # Startup recovery
        recovered = await mgr.recover_interrupted_jobs(db_session)
        assert recovered == 1

        await db_session.refresh(job)
        assert job.state == JobState.PAUSED

    @pytest.mark.asyncio
    async def test_recovery_resets_in_progress_items(
        self,
        db_session: AsyncSession,
        session_factory: async_sessionmaker[Any],
    ) -> None:
        mgr = _make_manager(session_factory)
        job = await mgr.create_job(
            session=db_session,
            job_type=JobType.FILE_CONVERT,
            display_name="With Items",
            config={},
        )

        mgr.transition(job, JobState.RUNNING)

        # Add some items in various states
        db_session.add(
            UtilityJobItem(
                id="ip-1",
                job_id=job.id,
                item_index=0,
                state=ItemState.IN_PROGRESS,
                operation="test",
                started_at="2026-05-01T00:00:00+00:00",
                worker_id=2,
            )
        )
        db_session.add(
            UtilityJobItem(
                id="done-1",
                job_id=job.id,
                item_index=1,
                state=ItemState.COMPLETED,
                operation="test",
            )
        )
        await db_session.flush()

        await mgr.recover_interrupted_jobs(db_session)

        # IN_PROGRESS → PENDING
        ip_item = await db_session.get(UtilityJobItem, "ip-1")
        assert ip_item is not None
        assert ip_item.state == ItemState.PENDING
        assert ip_item.started_at is None
        assert ip_item.worker_id is None

        # COMPLETED stays COMPLETED
        done_item = await db_session.get(UtilityJobItem, "done-1")
        assert done_item is not None
        assert done_item.state == ItemState.COMPLETED


# ── Queue Ordering ─────────────────────────────────────────────


class TestQueueOrdering:
    """Verify FIFO queue ordering and resume priority."""

    @pytest.mark.asyncio
    async def test_fifo_order_maintained(
        self,
        db_session: AsyncSession,
        session_factory: async_sessionmaker[Any],
    ) -> None:
        mgr = _make_manager(session_factory)
        jobs = []
        for i in range(3):
            job = await mgr.create_job(
                session=db_session,
                job_type=JobType.FILE_CONVERT,
                display_name=f"Job {i}",
                config={},
            )
            jobs.append(job)

        assert jobs[0].queue_position == 0
        assert jobs[1].queue_position == 1
        assert jobs[2].queue_position == 2

    @pytest.mark.asyncio
    async def test_resumed_job_gets_priority(
        self,
        db_session: AsyncSession,
        session_factory: async_sessionmaker[Any],
    ) -> None:
        """Resumed job goes to position 0, ahead of queued jobs."""
        mgr = _make_manager(session_factory)

        # Queue two jobs (positions 0 and 1)
        await mgr.create_job(
            session=db_session,
            job_type=JobType.FILE_CONVERT,
            display_name="Queued 1",
            config={},
        )
        await mgr.create_job(
            session=db_session,
            job_type=JobType.FILE_CONVERT,
            display_name="Queued 2",
            config={},
        )

        # Create a paused job and resume it
        paused = UtilityJob(
            id="paused-priority",
            job_type=JobType.FILE_CONVERT,
            display_name="Resumed",
            state=JobState.PAUSED,
            config="{}",
            total_items=0,
            completed_items=0,
            failed_items=0,
            skipped_items=0,
            warning_count=0,
            queue_position=99,
        )
        db_session.add(paused)
        await db_session.flush()

        await mgr.resume_job(db_session, "paused-priority")
        assert paused.queue_position == 0


# ── Worker Pool Integration ────────────────────────────────────


class TestWorkerPoolIntegration:
    """Verify WorkerPool processes items correctly in integration."""

    @pytest.mark.asyncio
    async def test_batch_results_checkpointed(
        self,
        db_session: AsyncSession,
        session_factory: async_sessionmaker[Any],
    ) -> None:
        """Item results from WorkerPool are persisted to DB."""
        mgr = _make_manager(session_factory)
        job = await mgr.create_job(
            session=db_session,
            job_type=JobType.FILE_CONVERT,
            display_name="Checkpoint Test",
            config={"count": 3},
        )

        await _run_job_to_completion(mgr, db_session, job)

        # Verify each item has duration and state snapshots
        result = await db_session.execute(
            select(UtilityJobItem)
            .where(UtilityJobItem.job_id == job.id)
            .order_by(UtilityJobItem.item_index)
        )
        items = list(result.scalars().all())
        for item in items:
            assert item.state == ItemState.COMPLETED
            assert item.duration_ms is not None
            assert item.before_state is not None
            assert item.after_state is not None
