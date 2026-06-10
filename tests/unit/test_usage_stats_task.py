"""Tests for usage-stats telemetry scheduler tasks."""

from __future__ import annotations

from unittest.mock import AsyncMock

from pullbox.core.scheduler import get_registered_tasks


def test_usage_stats_daily_task_is_registered() -> None:
    import pullbox.tasks.usage_stats_task  # noqa: F401

    task = next(task for task in get_registered_tasks() if task.task_id == "send_usage_stats")

    assert task.display_name == "Send Anonymous Usage Stats"
    assert task.trigger == "cron"
    assert task.trigger_kwargs["hour"] == 8
    assert task.trigger_kwargs["minute"] == 0
    assert task.exclusive is True


async def test_usage_stats_daily_task_delegates_to_guarded_sender(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    send = AsyncMock()
    monkeypatch.setattr("pullbox.tasks.usage_stats_task.send_usage_stats_ping", send)

    from pullbox.tasks.usage_stats_task import send_usage_stats

    await send_usage_stats()

    send.assert_awaited_once_with()
