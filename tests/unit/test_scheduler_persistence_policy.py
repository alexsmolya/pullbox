"""Tests for scheduler task-stat persistence policy helpers."""

from __future__ import annotations

from pullbox.core.scheduler_persistence_policy import (
    coarse_persist_due,
    is_hot_task,
    should_persist_task_stat,
)
from pullbox.core.scheduler_stats import TaskStats


def test_is_hot_task_uses_effective_interval_threshold() -> None:
    intervals = {
        "monitor_downloads": 3,
        "sync_recent": 300,
        "daily": 86_400,
        "unknown": None,
    }

    assert is_hot_task("monitor_downloads", intervals, hot_task_interval_seconds=300) is True
    assert is_hot_task("sync_recent", intervals, hot_task_interval_seconds=300) is False
    assert is_hot_task("daily", intervals, hot_task_interval_seconds=300) is False
    assert is_hot_task("unknown", intervals, hot_task_interval_seconds=300) is False
    assert is_hot_task("missing", intervals, hot_task_interval_seconds=300) is False


def test_coarse_persist_due_uses_missing_timestamp_or_elapsed_window() -> None:
    assert coarse_persist_due(
        "monitor_downloads",
        {},
        now=1_100.0,
        hot_task_persist_window_seconds=300.0,
    )
    assert not coarse_persist_due(
        "monitor_downloads",
        {"monitor_downloads": 1_000.0},
        now=1_100.0,
        hot_task_persist_window_seconds=300.0,
    )
    assert coarse_persist_due(
        "monitor_downloads",
        {"monitor_downloads": 1_000.0},
        now=1_301.0,
        hot_task_persist_window_seconds=300.0,
    )


def test_should_persist_task_stat_keeps_hot_task_throttling_rules() -> None:
    intervals = {"monitor_downloads": 3}
    last_persisted_at = {"monitor_downloads": 1_000.0}
    last_status = {"monitor_downloads": "completed"}

    assert not should_persist_task_stat(
        "monitor_downloads",
        TaskStats(last_status="completed"),
        trigger_type="scheduled",
        reason="completed",
        interval_seconds_by_task=intervals,
        last_persisted_at=last_persisted_at,
        last_persisted_status=last_status,
        now=1_100.0,
        hot_task_interval_seconds=300,
        hot_task_persist_window_seconds=300.0,
    )
    assert should_persist_task_stat(
        "monitor_downloads",
        TaskStats(last_status="completed"),
        trigger_type="manual",
        reason="completed",
        interval_seconds_by_task=intervals,
        last_persisted_at=last_persisted_at,
        last_persisted_status=last_status,
        now=1_100.0,
        hot_task_interval_seconds=300,
        hot_task_persist_window_seconds=300.0,
    )
    assert should_persist_task_stat(
        "monitor_downloads",
        TaskStats(last_status="failed"),
        trigger_type="scheduled",
        reason="failed",
        interval_seconds_by_task=intervals,
        last_persisted_at=last_persisted_at,
        last_persisted_status=last_status,
        now=1_100.0,
        hot_task_interval_seconds=300,
        hot_task_persist_window_seconds=300.0,
    )
    assert not should_persist_task_stat(
        "monitor_downloads",
        TaskStats(last_status="completed"),
        trigger_type="scheduled",
        reason="overlap",
        interval_seconds_by_task=intervals,
        last_persisted_at=last_persisted_at,
        last_persisted_status=last_status,
        now=1_100.0,
        hot_task_interval_seconds=300,
        hot_task_persist_window_seconds=300.0,
    )


def test_should_persist_task_stat_always_persists_non_hot_tasks() -> None:
    assert should_persist_task_stat(
        "daily_sync",
        TaskStats(last_status="completed"),
        trigger_type="scheduled",
        reason="completed",
        interval_seconds_by_task={"daily_sync": 86_400},
        last_persisted_at={},
        last_persisted_status={},
        now=1_100.0,
        hot_task_interval_seconds=300,
        hot_task_persist_window_seconds=300.0,
    )
