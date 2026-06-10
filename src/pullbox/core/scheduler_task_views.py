"""Presentation helpers for scheduler task views."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pullbox.core.scheduler_stats import TaskStats

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Set


def build_job_summaries(jobs: Iterable[Any]) -> list[dict[str, str]]:
    """Return summary info for APScheduler jobs."""
    return [
        {
            "id": job.id,
            "name": job.name,
            "next_run_time": str(getattr(job, "next_run_time", None)),
            "trigger": str(job.trigger),
        }
        for job in jobs
    ]


def build_scheduled_task_views(
    jobs: Iterable[Any],
    *,
    task_stats: Mapping[str, TaskStats],
    display_names: Mapping[str, str],
    running_counts: Mapping[str, int],
    queued_task_ids: Set[str],
    manual_queue_position: Callable[[str], int | None],
) -> list[dict[str, Any]]:
    """Return detailed scheduled task rows for the UI."""
    tasks: list[dict[str, Any]] = []
    for job in jobs:
        if job.id.endswith("_manual"):
            continue
        stats = task_stats.get(job.id, TaskStats())
        next_run_time = getattr(job, "next_run_time", None)
        tasks.append(
            {
                "task_id": job.id,
                "name": display_names.get(job.id, job.id.replace("_", " ").title()),
                "interval": str(job.trigger),
                "next_run_time": next_run_time.isoformat() if next_run_time else None,
                "last_execution": stats.last_execution,
                "last_duration_seconds": stats.last_duration_seconds,
                "last_status": stats.last_status,
                "last_missed_at": stats.last_missed_at,
                "missed_count": stats.missed_count,
                "last_overlap_at": stats.last_overlap_at,
                "overlap_count": stats.overlap_count,
                "last_exclusive_block_at": stats.last_exclusive_block_at,
                "exclusive_block_count": stats.exclusive_block_count,
                "running_since": stats.running_since,
                "is_running": running_counts.get(job.id, 0) > 0,
                "is_queued": job.id in queued_task_ids,
                "manual_queue_position": manual_queue_position(job.id),
            }
        )
    return tasks
