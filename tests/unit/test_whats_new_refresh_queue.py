"""Tests for the What's New refresh queue coordinator."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import date
from typing import TYPE_CHECKING

from pullbox.services.whats_new_refresh_queue import (
    RefreshQueueStatus,
    StartupRefreshStatus,
    WhatsNewRefreshCoordinator,
    refresh_whats_new_cache_if_needed,
    run_whats_new_refresh,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from sqlalchemy.ext.asyncio import AsyncSession


class _BackgroundTasks:
    def __init__(self) -> None:
        self.tasks: list[object] = []

    def add_task(self, func: object, *args: object, **kwargs: object) -> None:
        self.tasks.append((func, args, kwargs))


class TestWhatsNewRefreshCoordinator:
    async def test_queue_refresh_adds_background_task(self) -> None:
        background_tasks = _BackgroundTasks()
        coordinator = WhatsNewRefreshCoordinator()

        result = await coordinator.queue_refresh(background_tasks)

        assert result.status == RefreshQueueStatus.QUEUED
        assert result.message == "What's New refresh queued."
        assert len(background_tasks.tasks) == 1

    async def test_queue_refresh_rejects_when_refresh_is_running(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        async def runner() -> None:
            started.set()
            await release.wait()

        background_tasks = _BackgroundTasks()
        coordinator = WhatsNewRefreshCoordinator(runner=runner)
        result = await coordinator.queue_refresh(background_tasks)
        assert result.status == RefreshQueueStatus.QUEUED

        func, args, kwargs = background_tasks.tasks[0]  # type: ignore[misc]
        running_task = asyncio.create_task(func(*args, **kwargs))  # type: ignore[operator]
        await started.wait()

        try:
            second = await coordinator.queue_refresh(background_tasks)

            assert second.status == RefreshQueueStatus.ALREADY_RUNNING
            assert second.message == "What's New refresh is already in progress."
            assert len(background_tasks.tasks) == 1
        finally:
            release.set()
            await running_task

    async def test_queue_refresh_allows_new_run_after_completion(self) -> None:
        background_tasks = _BackgroundTasks()
        coordinator = WhatsNewRefreshCoordinator()

        first = await coordinator.queue_refresh(background_tasks)
        func, args, kwargs = background_tasks.tasks[0]  # type: ignore[misc]
        await func(*args, **kwargs)  # type: ignore[operator]
        second = await coordinator.queue_refresh(background_tasks)

        assert first.status == RefreshQueueStatus.QUEUED
        assert second.status == RefreshQueueStatus.QUEUED
        assert len(background_tasks.tasks) == 2


class _SuccessfulClient:
    def __init__(self) -> None:
        self.current_week_calls = 0
        self.upcoming_calls = 0

    async def get_current_week(self) -> dict[str, object]:
        self.current_week_calls += 1
        return {"store_date": "2026-05-13", "count": 1, "issues": []}

    async def get_upcoming(self) -> dict[str, object]:
        self.upcoming_calls += 1
        return {"weeks": [], "lookahead_weeks": 8}


class _FailingClient:
    async def get_current_week(self) -> dict[str, object]:
        msg = "upstream unavailable"
        raise RuntimeError(msg)

    async def get_upcoming(self) -> dict[str, object]:
        return {"weeks": [], "lookahead_weeks": 8}


class SessionFactory:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @asynccontextmanager
    async def __call__(self) -> AsyncGenerator[AsyncSession, None]:
        yield self._session


async def test_run_whats_new_refresh_commits_cache_rows(
    db_session: AsyncSession,
) -> None:
    await run_whats_new_refresh(
        session_factory=SessionFactory(db_session),
        client=_SuccessfulClient(),
    )

    from pullbox.services.whats_new_cache_service import WhatsNewCacheService

    cache = WhatsNewCacheService()
    current = await cache.get_latest_current_week(db_session)
    upcoming = await cache.get_upcoming(db_session)

    assert current is not None
    assert current.payload["count"] == 1
    assert upcoming is not None
    assert upcoming.payload["lookahead_weeks"] == 8


async def test_startup_refresh_runs_when_cache_is_missing(db_session: AsyncSession) -> None:
    client = _SuccessfulClient()

    result = await refresh_whats_new_cache_if_needed(
        session_factory=SessionFactory(db_session),
        client=client,
    )

    assert result.status == StartupRefreshStatus.REFRESHED
    assert result.reason == "missing"
    assert client.current_week_calls == 1
    assert client.upcoming_calls == 1


async def test_startup_refresh_skips_when_cache_is_fresh(db_session: AsyncSession) -> None:
    from pullbox.services.whats_new_cache_service import WhatsNewCacheService

    client = _SuccessfulClient()
    cache = WhatsNewCacheService()
    await cache.upsert_current_week(
        db_session,
        store_date=date(2026, 5, 13),
        payload={"store_date": "2026-05-13", "count": 1, "issues": []},
    )
    await cache.upsert_upcoming(db_session, payload={"weeks": [], "lookahead_weeks": 8})
    await db_session.flush()

    result = await refresh_whats_new_cache_if_needed(
        session_factory=SessionFactory(db_session),
        client=client,
    )

    assert result.status == StartupRefreshStatus.SKIPPED
    assert result.reason == "fresh"
    assert client.current_week_calls == 0
    assert client.upcoming_calls == 0


async def test_startup_refresh_failure_does_not_raise(db_session: AsyncSession) -> None:
    result = await refresh_whats_new_cache_if_needed(
        session_factory=SessionFactory(db_session),
        client=_FailingClient(),
    )

    assert result.status == StartupRefreshStatus.FAILED
    assert result.reason == "missing"
