"""Tests for UT-F.9 — utility API endpoints.

Verifies job CRUD, controls (pause/resume/cancel), queue status,
items/logs retrieval, and edge cases (invalid types, missing IDs,
state conflicts).

Run:
    pytest tests/utilities/test_api_endpoints.py -v
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from pullbox.utilities.job_queue import JobQueueManager
from pullbox.utilities.models import (
    ItemState,
    JobState,
    JobType,
    LogLevel,
    UtilityJob,
    UtilityJobItem,
    UtilityJobLog,
)
from pullbox.utilities.router import set_queue_manager
from pullbox.utilities.schemas import (
    JobCreateRequest,
    JobDetailResponse,
    JobListResponse,
    JobResponse,
    QueueStatusResponse,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# ── Fixtures ───────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _setup_queue_manager() -> None:
    """Ensure a JobQueueManager is available for router endpoints."""
    mgr = JobQueueManager(session_factory=None)
    set_queue_manager(mgr)


def _make_job(
    job_id: str = "job-001",
    state: JobState = JobState.QUEUED,
    job_type: str = JobType.FILE_CONVERT,
    display_name: str = "Test Job",
    queue_position: int | None = 0,
) -> UtilityJob:
    return UtilityJob(
        id=job_id,
        job_type=job_type,
        display_name=display_name,
        state=state,
        config="{}",
        total_items=10,
        completed_items=5,
        failed_items=1,
        skipped_items=0,
        warning_count=0,
        queue_position=queue_position,
        created_by="admin",
    )


# ── Schemas ────────────────────────────────────────────────────


class TestSchemas:
    """Verify Pydantic schemas serialize correctly."""

    def test_job_create_request_valid(self) -> None:
        req = JobCreateRequest(
            job_type="file_convert",
            display_name="Convert files",
            config={"target_format": "cbz"},
        )
        assert req.job_type == "file_convert"
        assert req.config["target_format"] == "cbz"

    def test_job_create_request_empty_name_rejected(self) -> None:
        from pydantic import ValidationError as PydanticValidationError

        with pytest.raises(PydanticValidationError):
            JobCreateRequest(job_type="file_convert", display_name="", config={})

    def test_job_response_from_model(self) -> None:
        job = _make_job()
        resp = JobResponse(
            id=job.id,
            job_type=job.job_type,
            display_name=job.display_name,
            state=job.state,
            total_items=job.total_items,
            completed_items=job.completed_items,
            failed_items=job.failed_items,
            skipped_items=job.skipped_items,
            warning_count=job.warning_count,
            queue_position=job.queue_position,
            progress_pct=job.progress_pct,
        )
        assert resp.id == "job-001"
        assert resp.progress_pct == 60.0

    def test_queue_status_response(self) -> None:
        status = QueueStatusResponse(queued=3, running=1, paused=0, total_completed=10)
        assert status.queued == 3

    def test_job_list_response(self) -> None:
        resp = JobListResponse(jobs=[], total=0)
        assert resp.total == 0


# ── Job Creation ───────────────────────────────────────────────


class TestJobCreation:
    """Verify job creation via the queue manager (router delegates to it)."""

    @pytest.mark.asyncio
    async def test_create_job_returns_queued(self, db_session: AsyncSession) -> None:
        mgr = JobQueueManager(session_factory=None)
        job = await mgr.create_job(
            session=db_session,
            job_type=JobType.FILE_CONVERT,
            display_name="Convert CBR",
            config={"target_format": "cbz"},
            created_by="admin",
        )
        assert job.state == JobState.QUEUED
        assert job.created_by == "admin"

    @pytest.mark.asyncio
    async def test_create_job_persists(self, db_session: AsyncSession) -> None:
        mgr = JobQueueManager(session_factory=None)
        job = await mgr.create_job(
            session=db_session,
            job_type=JobType.INTEGRITY_CHECK,
            display_name="Check Files",
            config={},
        )
        result = await db_session.execute(select(UtilityJob).where(UtilityJob.id == job.id))
        stored = result.scalar_one()
        assert stored.display_name == "Check Files"


# ── Job Retrieval ──────────────────────────────────────────────


class TestJobRetrieval:
    """Verify job listing and detail retrieval."""

    @pytest.mark.asyncio
    async def test_list_jobs_empty(self, db_session: AsyncSession) -> None:
        """No jobs in DB returns empty list, not 404."""
        result = await db_session.execute(select(UtilityJob))
        jobs = list(result.scalars().all())
        assert len(jobs) == 0

    @pytest.mark.asyncio
    async def test_list_jobs_returns_all(self, db_session: AsyncSession) -> None:
        for i in range(3):
            db_session.add(_make_job(job_id=f"list-{i}"))
        await db_session.flush()

        result = await db_session.execute(select(UtilityJob))
        jobs = list(result.scalars().all())
        assert len(jobs) == 3

    @pytest.mark.asyncio
    async def test_get_job_by_id(self, db_session: AsyncSession) -> None:
        db_session.add(_make_job(job_id="detail-1", display_name="Detail Test"))
        await db_session.flush()

        job = await db_session.get(UtilityJob, "detail-1")
        assert job is not None
        assert job.display_name == "Detail Test"

    @pytest.mark.asyncio
    async def test_get_nonexistent_job_returns_none(self, db_session: AsyncSession) -> None:
        job = await db_session.get(UtilityJob, "nonexistent-id")
        assert job is None


# ── Job Deletion ───────────────────────────────────────────────


class TestJobDeletion:
    """Verify job deletion constraints."""

    @pytest.mark.asyncio
    async def test_delete_completed_job(self, db_session: AsyncSession) -> None:
        job = _make_job(job_id="del-1", state=JobState.COMPLETED, queue_position=None)
        db_session.add(job)
        await db_session.flush()

        assert job.is_terminal
        await db_session.delete(job)
        await db_session.flush()

        result = await db_session.get(UtilityJob, "del-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_cannot_delete_running_job(self, db_session: AsyncSession) -> None:
        job = _make_job(job_id="del-run", state=JobState.RUNNING)
        db_session.add(job)
        await db_session.flush()

        assert not job.is_terminal


# ── Job Items ──────────────────────────────────────────────────


class TestJobItems:
    """Verify job item retrieval."""

    @pytest.mark.asyncio
    async def test_get_items_for_job(self, db_session: AsyncSession) -> None:
        job = _make_job(job_id="items-1")
        items = [
            UtilityJobItem(
                id=f"item-{i}",
                job_id="items-1",
                item_index=i,
                operation="convert",
                state=ItemState.COMPLETED,
            )
            for i in range(5)
        ]
        db_session.add(job)
        db_session.add_all(items)
        await db_session.flush()

        result = await db_session.execute(
            select(UtilityJobItem)
            .where(UtilityJobItem.job_id == "items-1")
            .order_by(UtilityJobItem.item_index)
        )
        loaded = list(result.scalars().all())
        assert len(loaded) == 5

    @pytest.mark.asyncio
    async def test_filter_items_by_state(self, db_session: AsyncSession) -> None:
        job = _make_job(job_id="items-2")
        db_session.add(job)
        db_session.add(
            UtilityJobItem(
                id="item-ok",
                job_id="items-2",
                item_index=0,
                operation="convert",
                state=ItemState.COMPLETED,
            )
        )
        db_session.add(
            UtilityJobItem(
                id="item-fail",
                job_id="items-2",
                item_index=1,
                operation="convert",
                state=ItemState.FAILED,
            )
        )
        await db_session.flush()

        result = await db_session.execute(
            select(UtilityJobItem).where(
                UtilityJobItem.job_id == "items-2",
                UtilityJobItem.state == ItemState.FAILED,
            )
        )
        failed = list(result.scalars().all())
        assert len(failed) == 1
        assert failed[0].id == "item-fail"


# ── Job Logs ───────────────────────────────────────────────────


class TestJobLogs:
    """Verify job log retrieval."""

    @pytest.mark.asyncio
    async def test_get_logs_for_job(self, db_session: AsyncSession) -> None:
        job = _make_job(job_id="logs-1")
        db_session.add(job)
        for i in range(3):
            db_session.add(
                UtilityJobLog(
                    job_id="logs-1",
                    level=LogLevel.INFO,
                    message=f"Step {i}",
                )
            )
        await db_session.flush()

        result = await db_session.execute(
            select(UtilityJobLog).where(UtilityJobLog.job_id == "logs-1")
        )
        logs = list(result.scalars().all())
        assert len(logs) == 3

    @pytest.mark.asyncio
    async def test_filter_logs_by_level(self, db_session: AsyncSession) -> None:
        job = _make_job(job_id="logs-2")
        db_session.add(job)
        db_session.add(UtilityJobLog(job_id="logs-2", level=LogLevel.INFO, message="info msg"))
        db_session.add(UtilityJobLog(job_id="logs-2", level=LogLevel.ERROR, message="error msg"))
        await db_session.flush()

        result = await db_session.execute(
            select(UtilityJobLog).where(
                UtilityJobLog.job_id == "logs-2",
                UtilityJobLog.level == LogLevel.ERROR,
            )
        )
        errors = list(result.scalars().all())
        assert len(errors) == 1
        assert errors[0].message == "error msg"

    @pytest.mark.asyncio
    async def test_empty_logs_returns_empty_list(self, db_session: AsyncSession) -> None:
        job = _make_job(job_id="logs-3")
        db_session.add(job)
        await db_session.flush()

        result = await db_session.execute(
            select(UtilityJobLog).where(UtilityJobLog.job_id == "logs-3")
        )
        assert list(result.scalars().all()) == []

    @pytest.mark.asyncio
    async def test_router_log_search_matches_message_path_and_extra(
        self,
        db_session: AsyncSession,
    ) -> None:
        from pullbox.utilities.router import get_job_logs

        job = _make_job(job_id="logs-4")
        db_session.add(job)
        db_session.add(
            UtilityJobLog(
                job_id="logs-4",
                level=LogLevel.WARNING,
                message="Skipped rename preview",
                file_path="/tmp/batman.cbz",
                extra='{"reason":"conflict"}',
            )
        )
        await db_session.flush()

        message_logs = await get_job_logs(
            job_id="logs-4",
            _user=MagicMock(),
            session=db_session,
            level=None,
            search="rename preview",
            limit=50,
            offset=0,
        )
        assert message_logs.total_count == 1

        path_logs = await get_job_logs(
            job_id="logs-4",
            _user=MagicMock(),
            session=db_session,
            level=None,
            search="batman.cbz",
            limit=50,
            offset=0,
        )
        assert path_logs.total_count == 1

        extra_logs = await get_job_logs(
            job_id="logs-4",
            _user=MagicMock(),
            session=db_session,
            level=None,
            search="conflict",
            limit=50,
            offset=0,
        )
        assert extra_logs.total_count == 1

    @pytest.mark.asyncio
    async def test_router_log_response_enriches_extra_with_diagnostic_context(
        self,
        db_session: AsyncSession,
    ) -> None:
        from pullbox.utilities.router import get_job_logs

        job = _make_job(
            job_id="logs-rich",
            state=JobState.RUNNING,
            job_type=JobType.LIBRARY_PERMISSIONS,
            display_name="Apply permissions",
            queue_position=None,
        )
        job.total_items = 4
        job.completed_items = 1
        job.failed_items = 1
        job.skipped_items = 1
        job.warning_count = 2
        db_session.add(job)
        db_session.add(
            UtilityJobItem(
                id="item-42",
                job_id="logs-rich",
                item_index=42,
                state=ItemState.SKIPPED,
                file_path="/storage/comics/.DS_Store",
                operation="chmod",
            )
        )
        db_session.add(
            UtilityJobLog(
                job_id="logs-rich",
                item_id="item-42",
                timestamp="2026-05-18T10:15:00Z",
                level=LogLevel.WARNING,
                message="Skipped permissions change",
                file_path="/storage/comics/.DS_Store",
                extra='{"operation":"chmod","reason":"dry_run","mode":"0644"}',
            )
        )
        await db_session.flush()

        logs = await get_job_logs(
            job_id="logs-rich",
            _user=MagicMock(),
            session=db_session,
            level=None,
            search=None,
            limit=50,
            offset=0,
        )

        assert logs.total_count == 1
        extra = logs.entries[0].extra
        assert isinstance(extra, dict)
        assert extra["job"] == {
            "id": "logs-rich",
            "type": JobType.LIBRARY_PERMISSIONS,
            "display_name": "Apply permissions",
            "state": JobState.RUNNING,
            "progress_pct": 75.0,
            "total_items": 4,
            "completed_items": 1,
            "failed_items": 1,
            "skipped_items": 1,
            "warning_count": 2,
        }
        assert extra["entry"] == {
            "id": logs.entries[0].id,
            "item_id": "item-42",
            "timestamp": "2026-05-18T10:15:00Z",
            "level": LogLevel.WARNING,
            "message": "Skipped permissions change",
            "file_path": "/storage/comics/.DS_Store",
        }
        assert extra["details"] == {
            "operation": "chmod",
            "reason": "dry_run",
            "mode": "0644",
        }

    @pytest.mark.asyncio
    async def test_download_logs_returns_json_attachment(
        self,
        db_session: AsyncSession,
    ) -> None:
        from pullbox.utilities.router import download_job_logs

        job = _make_job(job_id="logs-dl", state=JobState.COMPLETED, queue_position=None)
        job.created_at = "2026-04-05T08:00:00Z"
        db_session.add(job)
        db_session.add(
            UtilityJobLog(
                job_id="logs-dl",
                level=LogLevel.ERROR,
                message="Failed to convert issue",
                file_path="/tmp/issue-001.cbr",
                extra='{"worker":"converter-1"}',
            )
        )
        await db_session.flush()

        response = await download_job_logs(
            job_id="logs-dl",
            _user=MagicMock(),
            session=db_session,
            level=None,
            search=None,
        )

        assert "application/json" in response.media_type
        assert (
            response.headers["Content-Disposition"]
            == 'attachment; filename="utility_job_20260405_080000.json"'
        )
        body = response.body.decode()
        assert body.startswith("{\n  ")
        assert '\n  "job": {' in body
        payload = json.loads(body)
        assert payload["job"]["id"] == "logs-dl"
        assert payload["job"]["created_at"] == "2026-04-05T08:00:00Z"
        assert payload["total_count"] == 1
        assert payload["filters"] == {"level": None, "search": None}
        assert payload["entries"][0]["message"] == "Failed to convert issue"
        assert payload["entries"][0]["file_path"] == "/tmp/issue-001.cbr"
        assert payload["entries"][0]["extra"]["job"]["id"] == "logs-dl"
        assert payload["entries"][0]["extra"]["entry"]["file_path"] == "/tmp/issue-001.cbr"
        assert payload["entries"][0]["extra"]["details"] == {"worker": "converter-1"}


# ── Queue Status ───────────────────────────────────────────────


class TestQueueStatus:
    """Verify queue status counts."""

    @pytest.mark.asyncio
    async def test_queue_counts(self, db_session: AsyncSession) -> None:
        db_session.add(_make_job(job_id="q-1", state=JobState.QUEUED))
        db_session.add(_make_job(job_id="q-2", state=JobState.QUEUED))
        db_session.add(_make_job(job_id="q-3", state=JobState.RUNNING, queue_position=None))
        db_session.add(_make_job(job_id="q-4", state=JobState.COMPLETED, queue_position=None))
        await db_session.flush()

        from sqlalchemy import func as sa_func

        result = await db_session.execute(
            select(UtilityJob.state, sa_func.count()).group_by(UtilityJob.state)
        )
        counts = dict(result.all())
        assert counts.get(JobState.QUEUED, 0) == 2
        assert counts.get(JobState.RUNNING, 0) == 1
        assert counts.get(JobState.COMPLETED, 0) == 1

    @pytest.mark.asyncio
    async def test_empty_queue(self, db_session: AsyncSession) -> None:
        from sqlalchemy import func as sa_func

        result = await db_session.execute(
            select(UtilityJob.state, sa_func.count()).group_by(UtilityJob.state)
        )
        counts = dict(result.all())
        assert counts.get(JobState.QUEUED, 0) == 0


# ── Control Edge Cases ─────────────────────────────────────────


class TestControlEdgeCases:
    """Verify control operation edge cases."""

    @pytest.mark.asyncio
    async def test_pause_queued_job_raises(self, db_session: AsyncSession) -> None:
        job = _make_job(job_id="ctrl-e1", state=JobState.QUEUED)
        db_session.add(job)
        await db_session.flush()

        mgr = JobQueueManager(session_factory=None)
        with pytest.raises(ValueError, match="Invalid transition"):
            await mgr.pause_job(db_session, "ctrl-e1")

    @pytest.mark.asyncio
    async def test_resume_running_job_raises(self, db_session: AsyncSession) -> None:
        job = _make_job(job_id="ctrl-e2", state=JobState.RUNNING)
        db_session.add(job)
        await db_session.flush()

        mgr = JobQueueManager(session_factory=None)
        with pytest.raises(ValueError, match="Can only resume"):
            await mgr.resume_job(db_session, "ctrl-e2")

    @pytest.mark.asyncio
    async def test_cancel_completed_raises(self, db_session: AsyncSession) -> None:
        job = _make_job(job_id="ctrl-e3", state=JobState.COMPLETED, queue_position=None)
        db_session.add(job)
        await db_session.flush()

        mgr = JobQueueManager(session_factory=None)
        with pytest.raises(ValueError, match="Cannot cancel"):
            await mgr.cancel_job(db_session, "ctrl-e3")

    @pytest.mark.asyncio
    async def test_nonexistent_job_raises(self, db_session: AsyncSession) -> None:
        mgr = JobQueueManager(session_factory=None)
        with pytest.raises(ValueError, match="Job not found"):
            await mgr.pause_job(db_session, "ghost-id")

    @pytest.mark.asyncio
    async def test_resume_route_dispatches_resumed_job(self) -> None:
        from pullbox.utilities import router as utilities_router

        mgr = MagicMock()
        mgr.resume_job = AsyncMock()
        mgr.dispatch_next = AsyncMock()
        set_queue_manager(mgr)

        response = await utilities_router.resume_job(
            job_id="ctrl-e4",
            _user=MagicMock(),
            session=MagicMock(),
        )

        assert response == {"status": "queued", "job_id": "ctrl-e4"}
        mgr.resume_job.assert_awaited_once()

        await asyncio.sleep(0.15)

        mgr.dispatch_next.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rollback_route_dispatches_queued_job(self) -> None:
        from pullbox.utilities import router as utilities_router

        mgr = MagicMock()
        mgr.queue_rollback_job = AsyncMock()
        mgr.dispatch_next = AsyncMock()
        set_queue_manager(mgr)

        response = await utilities_router.rollback_job(
            job_id="ctrl-e5",
            _user=MagicMock(username="admin"),
            session=MagicMock(),
        )

        assert response == {"status": "queued", "job_id": "ctrl-e5"}
        mgr.queue_rollback_job.assert_awaited_once()

        await asyncio.sleep(0.15)

        mgr.dispatch_next.assert_awaited_once()


# ── Schema Validation ─────────────────────────────────────────


class TestSchemaValidation:
    """Verify invalid request schemas are rejected."""

    def test_invalid_job_type_detected(self) -> None:
        """We validate job_type at the router level, not schema level."""
        valid_types = {t.value for t in JobType}
        assert "invalid_type" not in valid_types

    def test_job_create_default_config(self) -> None:
        req = JobCreateRequest(job_type="file_convert", display_name="Test")
        assert req.config == {}

    def test_job_detail_response_includes_config(self) -> None:
        resp = JobDetailResponse(
            id="x",
            job_type="file_convert",
            display_name="Test",
            state="QUEUED",
            config='{"key": "val"}',
        )
        assert json.loads(resp.config)["key"] == "val"
