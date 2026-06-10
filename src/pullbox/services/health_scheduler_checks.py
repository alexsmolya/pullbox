"""Scheduler-specific health check implementation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from pullbox.models.health import HealthStatus
from pullbox.services.health_helpers import (
    _STATUS_PRECEDENCE,
    _parse_optional_datetime,
    _scheduler_event_cleared,
    _scheduler_incident_message,
    _scheduler_stuck_threshold,
    _serialize_sub_check,
)
from pullbox.services.health_types import CheckOutcome, SubCheckOutcome

if TYPE_CHECKING:
    from pullbox.core.scheduler import PullboxScheduler

_SCHEDULER_EVENT_WINDOW_HOURS = 24


async def check_scheduler(scheduler: PullboxScheduler | None) -> CheckOutcome:
    """Verify the scheduler is running and tasks are executing cleanly."""
    if not scheduler:
        return CheckOutcome(
            component="scheduler",
            check_name="status",
            status=HealthStatus.UNHEALTHY,
            message="Not available",
            details={
                "checks": [
                    {
                        "name": "Scheduler",
                        "status": "unhealthy",
                        "message": "Scheduler was not injected",
                    }
                ]
            },
            actionable_guidance="The scheduler was not injected. Restart the application.",
        )

    if not scheduler.running:
        return CheckOutcome(
            component="scheduler",
            check_name="status",
            status=HealthStatus.UNHEALTHY,
            message="Not running",
            details={
                "checks": [
                    {
                        "name": "Scheduler",
                        "status": "unhealthy",
                        "message": "Background task scheduler has stopped",
                    }
                ]
            },
            actionable_guidance=(
                "The background task scheduler has stopped. Restart the Pullbox application."
            ),
        )

    now = datetime.now(UTC)
    jobs = scheduler.get_jobs()
    tasks = scheduler.get_scheduled_tasks()
    recent_window = timedelta(hours=_SCHEDULER_EVENT_WINDOW_HOURS)

    failed_tasks: list[str] = []
    overdue_tasks: list[str] = []
    missed_tasks: list[str] = []
    cleared_missed_tasks: list[str] = []
    overlap_tasks: list[str] = []
    cleared_overlap_tasks: list[str] = []
    exclusive_block_tasks: list[str] = []
    cleared_exclusive_block_tasks: list[str] = []
    stuck_tasks: list[str] = []

    for task_info in tasks:
        task_name = str(task_info.get("name") or task_info.get("task_id") or "Task")
        is_running = bool(task_info.get("is_running"))
        last_status = str(task_info.get("last_status") or "").lower()
        if last_status == "failed" and not is_running:
            failed_tasks.append(task_name)

        last_exec = _parse_optional_datetime(task_info.get("last_execution"))

        last_missed_at = _parse_optional_datetime(task_info.get("last_missed_at"))
        if last_missed_at and (now - last_missed_at) <= recent_window:
            if _scheduler_event_cleared(last_missed_at, last_exec):
                cleared_missed_tasks.append(task_name)
            else:
                missed_tasks.append(task_name)

        last_overlap_at = _parse_optional_datetime(task_info.get("last_overlap_at"))
        if last_overlap_at and (now - last_overlap_at) <= recent_window:
            if _scheduler_event_cleared(last_overlap_at, last_exec):
                cleared_overlap_tasks.append(task_name)
            else:
                overlap_tasks.append(task_name)

        last_exclusive_block_at = _parse_optional_datetime(task_info.get("last_exclusive_block_at"))
        if last_exclusive_block_at and (now - last_exclusive_block_at) <= recent_window:
            if _scheduler_event_cleared(last_exclusive_block_at, last_exec):
                cleared_exclusive_block_tasks.append(task_name)
            else:
                exclusive_block_tasks.append(task_name)

        running_since = _parse_optional_datetime(task_info.get("running_since"))
        if is_running and running_since is not None:
            running_for = now - running_since
            if running_for >= _scheduler_stuck_threshold(task_info):
                stuck_tasks.append(task_name)

        next_run = _parse_optional_datetime(task_info.get("next_run_time"))
        if not last_exec or not next_run:
            continue

        expected_interval = next_run - last_exec
        if expected_interval <= timedelta(0):
            continue

        since_last = now - last_exec
        if since_last > (expected_interval * 2):
            overdue_tasks.append(task_name)

    jobs = scheduler.get_jobs()
    sub_checks: list[SubCheckOutcome] = [
        SubCheckOutcome(
            check_name="scheduler_runtime",
            name="Scheduler runtime",
            status=HealthStatus.HEALTHY,
            message=f"Running with {len(jobs)} job(s)",
            details={"job_count": str(len(jobs))},
        ),
        SubCheckOutcome(
            check_name="failed_tasks",
            name="Failed tasks",
            status=HealthStatus.DEGRADED if failed_tasks else HealthStatus.HEALTHY,
            message=", ".join(failed_tasks) if failed_tasks else "No failed tasks",
        ),
        SubCheckOutcome(
            check_name="missed_executions",
            name="Missed executions",
            status=HealthStatus.DEGRADED if missed_tasks else HealthStatus.HEALTHY,
            message=_scheduler_incident_message(
                unresolved=missed_tasks,
                cleared=cleared_missed_tasks,
                none_message="No recent missed runs",
                cleared_label="Recent misses cleared by later successful runs",
            ),
        ),
        SubCheckOutcome(
            check_name="overlap_skips",
            name="Overlap skips",
            status=HealthStatus.DEGRADED if overlap_tasks else HealthStatus.HEALTHY,
            message=_scheduler_incident_message(
                unresolved=overlap_tasks,
                cleared=cleared_overlap_tasks,
                none_message="No recent overlap skips",
                cleared_label="Recent overlap skips cleared by later successful runs",
            ),
        ),
        SubCheckOutcome(
            check_name="exclusive_task_blocks",
            name="Exclusive task blocks",
            status=(HealthStatus.DEGRADED if exclusive_block_tasks else HealthStatus.HEALTHY),
            message=_scheduler_incident_message(
                unresolved=exclusive_block_tasks,
                cleared=cleared_exclusive_block_tasks,
                none_message="No recent exclusive-task blocks",
                cleared_label=("Recent exclusive-task blocks cleared by later successful runs"),
            ),
        ),
        SubCheckOutcome(
            check_name="stuck_tasks",
            name="Stuck tasks",
            status=HealthStatus.UNHEALTHY if stuck_tasks else HealthStatus.HEALTHY,
            message=", ".join(stuck_tasks) if stuck_tasks else "No stuck tasks detected",
        ),
        SubCheckOutcome(
            check_name="overdue_tasks",
            name="Overdue tasks",
            status=HealthStatus.DEGRADED if overdue_tasks else HealthStatus.HEALTHY,
            message=", ".join(overdue_tasks) if overdue_tasks else "No overdue tasks",
        ),
    ]

    worst = max(
        (check.status for check in sub_checks),
        key=lambda status: _STATUS_PRECEDENCE.get(status, 0),
        default=HealthStatus.UNKNOWN,
    )

    if stuck_tasks:
        message = "Stuck tasks detected"
        guidance = (
            "One or more scheduler tasks have been running far longer than expected. "
            "Inspect the task log output and restart the app if the task is hung."
        )
    elif failed_tasks:
        message = "Failed tasks detected"
        guidance = (
            "Some scheduled tasks last ended in a failed state. Check task logs and "
            "the System > Tasks page for the failing task."
        )
    elif missed_tasks:
        message = "Missed executions detected"
        guidance = (
            "Scheduler runs were missed recently. Check whether the app was paused, "
            "restarted, or blocked from running on schedule."
        )
    elif exclusive_block_tasks:
        message = "Exclusive task blocks detected"
        guidance = (
            "A task run was skipped because an exclusive maintenance task was already "
            "active. If this repeats often, review task exclusivity and schedule cadence."
        )
    elif overlap_tasks:
        message = "Overlap skips detected"
        guidance = (
            "Tasks are overlapping and getting skipped because prior runs are still "
            "active. Review task runtimes and scheduler cadence."
        )
    elif overdue_tasks:
        message = "Overdue tasks detected"
        guidance = (
            "Some scheduled tasks have not run in over twice their expected interval. "
            "Check application logs for errors."
        )
    else:
        message = "Running normally"
        guidance = ""

    return CheckOutcome(
        component="scheduler",
        check_name="status",
        status=worst,
        message=message,
        details={
            "checks": [_serialize_sub_check(check) for check in sub_checks],
            "job_count": str(len(jobs)),
            "failed": ", ".join(failed_tasks),
            "missed": ", ".join(missed_tasks),
            "missed_recent": ", ".join([*missed_tasks, *cleared_missed_tasks]),
            "overlap": ", ".join(overlap_tasks),
            "overlap_recent": ", ".join([*overlap_tasks, *cleared_overlap_tasks]),
            "exclusive_block": ", ".join(exclusive_block_tasks),
            "exclusive_block_recent": ", ".join(
                [*exclusive_block_tasks, *cleared_exclusive_block_tasks]
            ),
            "stuck": ", ".join(stuck_tasks),
            "overdue": ", ".join(overdue_tasks),
        },
        actionable_guidance=guidance,
        sub_checks=tuple(sub_checks),
    )
