"""Focused API coverage for utility history clearing."""

from __future__ import annotations

import os
import sys

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker  # noqa: TC002

from pullbox.services.auth_service import SESSION_COOKIE_NAME, AuthService
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

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

pytest_plugins = ["conftest_security"]

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-utilities-history")


def _csrf_header_for(client) -> dict[str, str]:  # type: ignore[no-untyped-def]
    token = client.cookies.get(SESSION_COOKIE_NAME) or ""
    csrf = AuthService.get_csrf_token_from_session(token) or ""
    return {"X-CSRF-Token": csrf}


@pytest.fixture(autouse=True)
def _setup_queue_manager() -> None:
    set_queue_manager(JobQueueManager(session_factory=None))


@pytest.fixture
async def seeded_jobs(
    sec_db: async_sessionmaker,
) -> None:
    async with sec_db() as session:
        terminal_states = [
            JobState.COMPLETED,
            JobState.FAILED,
            JobState.CANCELLED,
        ]
        for index, state in enumerate(terminal_states, start=1):
            job = UtilityJob(
                id=f"terminal-{index}",
                job_type=JobType.FILE_CONVERT,
                display_name=f"Terminal Job {index}",
                state=state,
                config="{}",
                total_items=2,
                completed_items=1,
                failed_items=1 if state != JobState.COMPLETED else 0,
                skipped_items=0,
                warning_count=0,
                queue_position=None,
                created_at=f"2026-04-05T08:0{index}:00Z",
            )
            session.add(job)
            await session.flush()
            item = UtilityJobItem(
                id=f"terminal-item-{index}",
                job_id=job.id,
                item_index=0,
                operation="convert",
                state=ItemState.COMPLETED,
            )
            session.add(item)
            session.add(
                UtilityJobLog(
                    job_id=job.id,
                    item_id=item.id,
                    level=LogLevel.INFO,
                    message=f"Terminal log {index}",
                )
            )

        running = UtilityJob(
            id="running-1",
            job_type=JobType.INTEGRITY_CHECK,
            display_name="Running Job",
            state=JobState.RUNNING,
            config="{}",
            total_items=5,
            completed_items=2,
            failed_items=0,
            skipped_items=0,
            warning_count=0,
            queue_position=None,
            created_at="2026-04-05T09:00:00Z",
        )
        session.add(running)
        await session.flush()
        running_item = UtilityJobItem(
            id="running-item-1",
            job_id=running.id,
            item_index=0,
            operation="check",
            state=ItemState.IN_PROGRESS,
        )
        session.add(running_item)
        session.add(
            UtilityJobLog(
                job_id=running.id,
                item_id=running_item.id,
                level=LogLevel.INFO,
                message="Running log",
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_clear_history_deletes_only_terminal_jobs(
    authenticated_client,
    sec_db: async_sessionmaker,
    seeded_jobs: None,
) -> None:  # type: ignore[no-untyped-def]
    response = await authenticated_client.delete(
        "/api/v1/utilities/history",
        headers=_csrf_header_for(authenticated_client),
    )

    assert response.status_code == 200
    assert response.json() == {"deleted": 3}

    async with sec_db() as session:
        jobs = list((await session.execute(select(UtilityJob.id, UtilityJob.state))).all())
        items_count = (
            await session.execute(select(func.count()).select_from(UtilityJobItem))
        ).scalar_one()
        logs_count = (
            await session.execute(select(func.count()).select_from(UtilityJobLog))
        ).scalar_one()

    assert jobs == [("running-1", JobState.RUNNING)]
    assert items_count == 1
    assert logs_count == 1


@pytest.mark.asyncio
async def test_clear_history_returns_zero_when_history_is_empty(
    authenticated_client,
) -> None:  # type: ignore[no-untyped-def]
    response = await authenticated_client.delete(
        "/api/v1/utilities/history",
        headers=_csrf_header_for(authenticated_client),
    )

    assert response.status_code == 200
    assert response.json() == {"deleted": 0}
