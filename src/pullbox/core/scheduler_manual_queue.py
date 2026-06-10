"""Pure scheduler manual-queue helpers."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable


@dataclass(frozen=True)
class ManualTaskRequest:
    """Queued manual task trigger metadata."""

    task_id: str
    trigger_request_id: str | None = None


def manual_queue_position(queue: Iterable[ManualTaskRequest], task_id: str) -> int | None:
    """Return a task's 1-based queue position, if it is queued."""
    for index, queued in enumerate(queue, start=1):
        if queued.task_id == task_id:
            return index
    return None


def rebalance_manual_queue(
    queue: Iterable[ManualTaskRequest],
    *,
    deferred_task_ids: Collection[str],
) -> deque[ManualTaskRequest]:
    """Return a queue with deferred manual tasks moved to the back."""
    regular: list[ManualTaskRequest] = []
    deferred: list[ManualTaskRequest] = []
    for queued in queue:
        if queued.task_id in deferred_task_ids:
            deferred.append(queued)
        else:
            regular.append(queued)
    return deque([*regular, *deferred])
