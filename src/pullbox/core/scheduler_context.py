"""Scheduler execution context helpers."""

from __future__ import annotations

from contextvars import ContextVar

current_trigger_type_var: ContextVar[str] = ContextVar(
    "pullbox_scheduler_trigger_type",
    default="scheduled",
)
current_run_id_var: ContextVar[str | None] = ContextVar(
    "pullbox_scheduler_run_id",
    default=None,
)


def get_current_task_trigger_type() -> str:
    """Return the active scheduler trigger type for the current task run."""
    return current_trigger_type_var.get()


def get_current_task_run_id() -> str | None:
    """Return the active scheduler execution run ID for the current task run."""
    return current_run_id_var.get()
