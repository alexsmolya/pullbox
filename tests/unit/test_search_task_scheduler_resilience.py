"""Scheduler resilience coverage for the wanted-search task."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import OperationalError

from pullbox.providers.base import ProviderRegistry
from pullbox.tasks import search_task


class _FakeResult:
    def all(self) -> list[tuple[str, str]]:
        return []


class _FakeSession:
    def __init__(self, factory: _FakeSessionFactory) -> None:
        self._factory = factory

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def execute(self, _stmt):  # type: ignore[no-untyped-def]
        return _FakeResult()

    async def commit(self) -> None:
        self._factory.commit_attempts += 1
        if self._factory.commit_attempts == 1:
            raise OperationalError("COMMIT", {}, Exception("database is locked"))

    async def rollback(self) -> None:
        self._factory.rollback_attempts += 1

    async def get(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        return None

    def add(self, *_args, **_kwargs) -> None:  # type: ignore[no-untyped-def]
        return None


class _FakeSessionFactory:
    def __init__(self) -> None:
        self.session_count = 0
        self.commit_attempts = 0
        self.rollback_attempts = 0

    def __call__(self) -> _FakeSession:
        self.session_count += 1
        return _FakeSession(self)


@pytest.mark.asyncio
async def test_search_wanted_retries_search_phase_after_sqlite_lock(monkeypatch) -> None:
    """The fan-out persistence phase should retry on transient SQLite locks."""
    factory = _FakeSessionFactory()
    search_mock = AsyncMock(side_effect=[{123: ["dummy"]}, {123: ["dummy"]}])

    monkeypatch.setattr(search_task, "get_session_factory", lambda: factory)
    monkeypatch.setattr(
        search_task,
        "build_registry",
        AsyncMock(return_value=(ProviderRegistry(), [])),
    )
    monkeypatch.setattr(search_task.SearchService, "search_wanted", search_mock)
    monkeypatch.setattr(
        search_task.BlocklistService,
        "filter_results",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(search_task, "sqlite_lock_retry_delay", lambda _attempt: 0.0)

    await search_task.search_wanted()

    # One failed fan-out commit, one successful retry, then one per-attempt
    # search-history commit for the now-visible no-match result.
    assert factory.commit_attempts == 3
    assert factory.rollback_attempts == 1
    assert factory.session_count == 3
    assert search_mock.await_count == 2
