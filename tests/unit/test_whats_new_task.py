"""Tests for What's New scheduler tasks."""

from __future__ import annotations

from pullbox.core.scheduler import get_registered_tasks


def test_whats_new_refresh_task_is_registered() -> None:
    import pullbox.tasks.whats_new_task  # noqa: F401

    task = next(
        task for task in get_registered_tasks() if task.task_id == "refresh_whats_new_cache"
    )

    assert task.display_name == "Refresh What's New Cache"
    assert task.trigger == "cron"
    assert task.trigger_kwargs["hour"] == 7
    assert task.trigger_kwargs["minute"] == 0
    assert task.exclusive is True
