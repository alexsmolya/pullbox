"""Runtime log persistence helpers for utility queue dispatch."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from pullbox.utilities.base_executor import RuntimeLogEntry


def persist_runtime_log_entries(
    session: Any,
    *,
    runtime_logs: Iterable[RuntimeLogEntry],
    persist_log: Callable[..., None],
    configured_level: str,
    job_id: str,
    item_id: str | None = None,
    default_file_path: str | None = None,
    worker_id: int | None = None,
    duration_ms: int | None = None,
) -> None:
    """Persist structured runtime log entries with shared queue context."""
    for runtime_log in runtime_logs:
        persist_log(
            session,
            configured_level=configured_level,
            job_id=job_id,
            item_id=item_id,
            level=runtime_log.level,
            message=runtime_log.message,
            file_path=runtime_log.file_path or default_file_path,
            extra=runtime_log.extra,
            worker_id=worker_id,
            duration_ms=duration_ms,
        )
