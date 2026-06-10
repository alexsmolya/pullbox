"""Context binding helpers for scheduler task execution."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from pullbox.core.scheduler_context import current_run_id_var, current_trigger_type_var

if TYPE_CHECKING:
    from contextvars import Token


@dataclass(frozen=True, slots=True)
class SchedulerRunContext:
    """Tokens and identifiers bound for one scheduler task run."""

    trigger_token: Token[str]
    run_token: Token[str | None]
    run_id: str


def bind_scheduler_run_context(
    *,
    task_id: str,
    trigger_type: str,
    trigger_request_id: str | None = None,
) -> SchedulerRunContext:
    """Bind contextvars and structlog context for one scheduler task run."""
    trigger_token = current_trigger_type_var.set(trigger_type)
    run_id = uuid.uuid4().hex
    run_token = current_run_id_var.set(run_id)
    structlog.contextvars.unbind_contextvars(
        "request_id",
        "trigger_request_id",
        "task_id",
        "trigger_type",
        "run_id",
        "task_run_id",
    )
    structlog.contextvars.bind_contextvars(
        task_id=task_id,
        trigger_type=trigger_type,
        run_id=run_id,
        task_run_id=run_id,
    )
    if trigger_request_id is not None:
        structlog.contextvars.bind_contextvars(trigger_request_id=trigger_request_id)
    return SchedulerRunContext(
        trigger_token=trigger_token,
        run_token=run_token,
        run_id=run_id,
    )


def reset_scheduler_run_context(context: SchedulerRunContext) -> None:
    """Reset contextvars and structlog bindings for a scheduler task run."""
    current_trigger_type_var.reset(context.trigger_token)
    current_run_id_var.reset(context.run_token)
    structlog.contextvars.unbind_contextvars(
        "task_id",
        "trigger_type",
        "run_id",
        "task_run_id",
        "trigger_request_id",
    )
