"""Tests for scheduler run context binding helpers."""

from __future__ import annotations

import structlog

from pullbox.core.scheduler_context import (
    get_current_task_run_id,
    get_current_task_trigger_type,
)
from pullbox.core.scheduler_run_context import (
    bind_scheduler_run_context,
    reset_scheduler_run_context,
)


def test_scheduler_run_context_binds_and_resets_contextvars() -> None:
    context = bind_scheduler_run_context(
        task_id="sync_series",
        trigger_type="manual",
        trigger_request_id="request-123",
    )

    bound = structlog.contextvars.get_contextvars()
    assert get_current_task_trigger_type() == "manual"
    assert get_current_task_run_id() == context.run_id
    assert bound["task_id"] == "sync_series"
    assert bound["trigger_type"] == "manual"
    assert bound["run_id"] == context.run_id
    assert bound["task_run_id"] == context.run_id
    assert bound["trigger_request_id"] == "request-123"

    reset_scheduler_run_context(context)

    bound_after_reset = structlog.contextvars.get_contextvars()
    assert get_current_task_trigger_type() == "scheduled"
    assert get_current_task_run_id() is None
    assert "task_id" not in bound_after_reset
    assert "trigger_request_id" not in bound_after_reset
