"""Tests for utility runtime log persistence helpers."""

from __future__ import annotations

from typing import Any

from pullbox.utilities.base_executor import RuntimeLogEntry
from pullbox.utilities.job_queue_runtime_logs import persist_runtime_log_entries


def test_persist_runtime_log_entries_applies_default_file_path_and_context() -> None:
    calls: list[dict[str, Any]] = []
    session = object()

    def persist_log(active_session: object, **kwargs: Any) -> None:
        assert active_session is session
        calls.append(kwargs)

    persist_runtime_log_entries(
        session,
        runtime_logs=[
            RuntimeLogEntry(level="INFO", message="Default path", extra={"step": 1}),
            RuntimeLogEntry(
                level="WARNING",
                message="Override path",
                file_path="/runtime/override.cbz",
            ),
        ],
        persist_log=persist_log,
        configured_level="INFO",
        job_id="job-1",
        item_id="item-1",
        default_file_path="/imports/default.cbz",
        worker_id=3,
        duration_ms=44,
    )

    assert calls == [
        {
            "configured_level": "INFO",
            "job_id": "job-1",
            "item_id": "item-1",
            "level": "INFO",
            "message": "Default path",
            "file_path": "/imports/default.cbz",
            "extra": {"step": 1},
            "worker_id": 3,
            "duration_ms": 44,
        },
        {
            "configured_level": "INFO",
            "job_id": "job-1",
            "item_id": "item-1",
            "level": "WARNING",
            "message": "Override path",
            "file_path": "/runtime/override.cbz",
            "extra": {},
            "worker_id": 3,
            "duration_ms": 44,
        },
    ]


def test_persist_runtime_log_entries_ignores_empty_logs() -> None:
    calls: list[dict[str, Any]] = []

    persist_runtime_log_entries(
        object(),
        runtime_logs=[],
        persist_log=lambda _session, **kwargs: calls.append(kwargs),
        configured_level="INFO",
        job_id="job-1",
    )

    assert calls == []


def test_persist_runtime_log_entries_supports_job_level_logs_without_item_context() -> None:
    calls: list[dict[str, Any]] = []

    persist_runtime_log_entries(
        object(),
        runtime_logs=[
            RuntimeLogEntry(
                level="INFO",
                message="Final detail",
                file_path="/logs/final.cbz",
            )
        ],
        persist_log=lambda _session, **kwargs: calls.append(kwargs),
        configured_level="INFO",
        job_id="job-1",
    )

    assert calls == [
        {
            "configured_level": "INFO",
            "job_id": "job-1",
            "item_id": None,
            "level": "INFO",
            "message": "Final detail",
            "file_path": "/logs/final.cbz",
            "extra": {},
            "worker_id": None,
            "duration_ms": None,
        }
    ]
