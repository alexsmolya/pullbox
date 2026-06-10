"""Pure scheduler task-stat persistence policy helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pullbox.core.scheduler_stats import TaskStats


def is_hot_task(
    task_id: str,
    interval_seconds_by_task: Mapping[str, int | None],
    *,
    hot_task_interval_seconds: int,
) -> bool:
    """Return True when a task's effective interval is below the hot-task threshold."""
    interval_seconds = interval_seconds_by_task.get(task_id)
    return interval_seconds is not None and interval_seconds < hot_task_interval_seconds


def coarse_persist_due(
    task_id: str,
    last_persisted_at: Mapping[str, float],
    *,
    now: float,
    hot_task_persist_window_seconds: float,
) -> bool:
    """Return True when a hot task's coarse persistence window has elapsed."""
    last_persisted = last_persisted_at.get(task_id)
    if last_persisted is None:
        return True
    return (now - last_persisted) >= hot_task_persist_window_seconds


def should_persist_task_stat(
    task_id: str,
    stats: TaskStats,
    *,
    trigger_type: str,
    reason: str,
    interval_seconds_by_task: Mapping[str, int | None],
    last_persisted_at: Mapping[str, float],
    last_persisted_status: Mapping[str, str | None],
    now: float,
    hot_task_interval_seconds: int,
    hot_task_persist_window_seconds: float,
) -> bool:
    """Decide whether a task-stat update should hit the DB now."""
    del stats

    if trigger_type == "manual":
        return True
    if not is_hot_task(
        task_id,
        interval_seconds_by_task,
        hot_task_interval_seconds=hot_task_interval_seconds,
    ):
        return True
    if reason in {"failed", "cancelled"}:
        return True

    last_status = last_persisted_status.get(task_id)
    if reason == "completed":
        if task_id not in last_persisted_at or not last_status:
            return True
        if last_status in {"failed", "cancelled"}:
            return True
        return coarse_persist_due(
            task_id,
            last_persisted_at,
            now=now,
            hot_task_persist_window_seconds=hot_task_persist_window_seconds,
        )
    return reason not in {"missed", "overlap", "exclusive_block"}
