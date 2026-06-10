"""Tests for utility job queue configuration helpers."""

from __future__ import annotations

from typing import Any

import pytest

from pullbox.models.config import DEFAULT_SYSTEM_CONFIG
from pullbox.utilities.job_queue_config import (
    DEFAULT_UTILITY_LOG_LEVEL,
    DEFAULT_UTILITY_WORKER_COUNT,
    get_utility_log_level,
    get_utility_worker_count,
)


class _ScalarResult:
    def __init__(self, value: str | None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> str | None:
        return self._value


class _FakeSession:
    def __init__(self, value: str | None) -> None:
        self.value = value

    async def execute(self, _stmt: Any) -> _ScalarResult:
        return _ScalarResult(self.value)


@pytest.mark.asyncio
async def test_worker_count_uses_default_when_missing() -> None:
    assert int(DEFAULT_SYSTEM_CONFIG["utility_worker_count"][0]) == DEFAULT_UTILITY_WORKER_COUNT

    count = await get_utility_worker_count(_FakeSession(None))

    assert count == DEFAULT_UTILITY_WORKER_COUNT


@pytest.mark.asyncio
async def test_worker_count_rejects_invalid_values() -> None:
    assert await get_utility_worker_count(_FakeSession("0")) == DEFAULT_UTILITY_WORKER_COUNT
    assert await get_utility_worker_count(_FakeSession("not-a-number")) == (
        DEFAULT_UTILITY_WORKER_COUNT
    )


@pytest.mark.asyncio
async def test_worker_count_accepts_positive_integer() -> None:
    assert await get_utility_worker_count(_FakeSession("4")) == 4


@pytest.mark.asyncio
async def test_log_level_defaults_and_normalizes_valid_values() -> None:
    assert str(DEFAULT_SYSTEM_CONFIG["utility_log_level"][0]).upper() == DEFAULT_UTILITY_LOG_LEVEL
    assert await get_utility_log_level(_FakeSession(None)) == DEFAULT_UTILITY_LOG_LEVEL
    assert await get_utility_log_level(_FakeSession("warning")) == "WARNING"


@pytest.mark.asyncio
async def test_log_level_rejects_unknown_values() -> None:
    assert await get_utility_log_level(_FakeSession("TRACE")) == DEFAULT_UTILITY_LOG_LEVEL
