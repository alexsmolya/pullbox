"""Tests for scheduler task view builders."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from pullbox.core.scheduler_stats import TaskStats
from pullbox.core.scheduler_task_views import (
    build_job_summaries,
    build_scheduled_task_views,
)


def test_build_job_summaries_returns_apscheduler_job_fields() -> None:
    job = SimpleNamespace(
        id="sync_series",
        name="sync_series",
        trigger="interval[0:05:00]",
        next_run_time=datetime(2026, 6, 7, 12, 0, tzinfo=UTC),
    )

    assert build_job_summaries([job]) == [
        {
            "id": "sync_series",
            "name": "sync_series",
            "next_run_time": "2026-06-07 12:00:00+00:00",
            "trigger": "interval[0:05:00]",
        }
    ]


def test_build_scheduled_task_views_skips_manual_jobs_and_includes_runtime_flags() -> None:
    next_run = datetime(2026, 6, 7, 12, 0, tzinfo=UTC)
    jobs = [
        SimpleNamespace(id="sync_series", trigger="interval[0:05:00]", next_run_time=next_run),
        SimpleNamespace(id="sync_series_manual", trigger="date", next_run_time=None),
    ]
    stats = TaskStats(
        last_execution="2026-06-07T11:00:00+00:00",
        last_duration_seconds=3.2,
        last_status="completed",
        overlap_count=2,
    )

    rows = build_scheduled_task_views(
        jobs,
        task_stats={"sync_series": stats},
        display_names={"sync_series": "Sync Series"},
        running_counts={"sync_series": 1},
        queued_task_ids={"sync_series"},
        manual_queue_position=lambda task_id: 2 if task_id == "sync_series" else None,
    )

    assert rows == [
        {
            "task_id": "sync_series",
            "name": "Sync Series",
            "interval": "interval[0:05:00]",
            "next_run_time": "2026-06-07T12:00:00+00:00",
            "last_execution": "2026-06-07T11:00:00+00:00",
            "last_duration_seconds": 3.2,
            "last_status": "completed",
            "last_missed_at": None,
            "missed_count": 0,
            "last_overlap_at": None,
            "overlap_count": 2,
            "last_exclusive_block_at": None,
            "exclusive_block_count": 0,
            "running_since": None,
            "is_running": True,
            "is_queued": True,
            "manual_queue_position": 2,
        }
    ]
