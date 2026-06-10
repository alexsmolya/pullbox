"""Tests for scheduler execution context helpers."""

from __future__ import annotations

from pullbox.core.scheduler_context import (
    current_run_id_var,
    current_trigger_type_var,
    get_current_task_run_id,
    get_current_task_trigger_type,
)


def test_scheduler_context_defaults_to_scheduled_trigger_without_run_id() -> None:
    assert get_current_task_trigger_type() == "scheduled"
    assert get_current_task_run_id() is None


def test_scheduler_context_getters_reflect_bound_contextvars() -> None:
    trigger_token = current_trigger_type_var.set("manual")
    run_token = current_run_id_var.set("run-123")

    try:
        assert get_current_task_trigger_type() == "manual"
        assert get_current_task_run_id() == "run-123"
    finally:
        current_trigger_type_var.reset(trigger_token)
        current_run_id_var.reset(run_token)
