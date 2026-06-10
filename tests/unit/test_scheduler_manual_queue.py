"""Tests for pure scheduler manual-queue helpers."""

from __future__ import annotations

from collections import deque

from pullbox.core.scheduler_manual_queue import (
    ManualTaskRequest,
    manual_queue_position,
    rebalance_manual_queue,
)


def test_manual_queue_position_returns_one_based_position() -> None:
    queue = deque(
        [
            ManualTaskRequest(task_id="sync_new_issues"),
            ManualTaskRequest(task_id="run_health_checks"),
            ManualTaskRequest(task_id="search_wanted"),
        ]
    )

    assert manual_queue_position(queue, "sync_new_issues") == 1
    assert manual_queue_position(queue, "search_wanted") == 3
    assert manual_queue_position(queue, "missing") is None


def test_rebalance_manual_queue_moves_deferred_tasks_to_the_back() -> None:
    queue = deque(
        [
            ManualTaskRequest(task_id="run_health_checks", trigger_request_id="req-1"),
            ManualTaskRequest(task_id="search_wanted"),
            ManualTaskRequest(task_id="sync_new_issues"),
            ManualTaskRequest(task_id="run_health_checks", trigger_request_id="req-2"),
        ]
    )

    rebalanced = rebalance_manual_queue(queue, deferred_task_ids={"run_health_checks"})

    assert [request.task_id for request in rebalanced] == [
        "search_wanted",
        "sync_new_issues",
        "run_health_checks",
        "run_health_checks",
    ]
    assert rebalanced[2].trigger_request_id == "req-1"
    assert rebalanced[3].trigger_request_id == "req-2"


def test_rebalance_manual_queue_returns_original_order_when_nothing_is_deferred() -> None:
    queue = deque(
        [
            ManualTaskRequest(task_id="search_wanted"),
            ManualTaskRequest(task_id="sync_new_issues"),
        ]
    )

    rebalanced = rebalance_manual_queue(queue, deferred_task_ids={"run_health_checks"})

    assert list(rebalanced) == list(queue)
    assert rebalanced is not queue
