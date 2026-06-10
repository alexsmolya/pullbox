"""Tests for the scheduler task registry helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pullbox.core.scheduler_registry import (
    RegisteredTask,
    get_registered_tasks,
    scheduled_task,
    task_registry,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _restore_task_registry() -> Iterator[None]:
    """Keep registry-helper tests from leaking scratch registrations."""
    original_registry = list(task_registry)
    yield
    task_registry.clear()
    task_registry.extend(original_registry)


def test_scheduled_task_registers_metadata_and_defaults_display_name() -> None:
    task_registry.clear()

    async def _task() -> None:
        return None

    decorated = scheduled_task(task_id="sync_new_issues", trigger="interval", hours=1)(_task)

    assert decorated is _task
    assert task_registry == [
        RegisteredTask(
            func=_task,
            task_id="sync_new_issues",
            trigger="interval",
            trigger_kwargs={"hours": 1},
            display_name="Sync New Issues",
            exclusive=False,
        )
    ]


def test_scheduled_task_preserves_explicit_display_name_and_exclusive_flag() -> None:
    task_registry.clear()

    async def _task() -> None:
        return None

    scheduled_task(
        task_id="run_health_checks",
        trigger="cron",
        display_name="Health",
        exclusive=True,
        hour=5,
    )(_task)

    [registered] = task_registry
    assert registered.display_name == "Health"
    assert registered.exclusive is True
    assert registered.trigger_kwargs == {"hour": 5}


def test_get_registered_tasks_returns_a_copy() -> None:
    task_registry.clear()

    async def _task() -> None:
        return None

    scheduled_task(task_id="cleanup_history", trigger="cron", hour=5)(_task)

    registered = get_registered_tasks()
    registered.clear()

    assert len(task_registry) == 1
