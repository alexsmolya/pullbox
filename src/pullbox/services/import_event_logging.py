"""Structured import event logging helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

from pullbox.core.log_sanitizer import sanitize_log_mapping, sanitize_log_string
from pullbox.models.import_job import ImportJobLog

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


IMPORT_ROOT_SUMMARY_EVENTS = frozenset(
    {
        "import_job_created",
        "import_scan_started",
        "import_scan_paused",
        "import_scan_cancelled",
        "import_scan_completed",
        "import_scan_failed",
        "import_ready_for_review",
        "import_confirmed",
        "import_execution_started",
        "import_completed",
        "import_pause_requested",
        "import_resume_requested",
        "import_cancel_requested",
        "import_rollback_requested",
        "import_rollback_started",
        "import_rollback_completed",
    }
)


class ImportLogger(Protocol):
    """Logger surface used by import event persistence."""

    def bind(self, **kwargs: object) -> Any: ...


def log_import_event(
    session: AsyncSession,
    job_id: int,
    level: str,
    event: str,
    *,
    message: str | None,
    detail_logger: ImportLogger,
    root_logger: ImportLogger,
    root_summary_events: frozenset[str] = IMPORT_ROOT_SUMMARY_EVENTS,
    data: dict[str, Any] | None = None,
) -> ImportJobLog:
    """Emit one structured import event to detail logs, summaries, and the DB."""
    sanitized_message = sanitize_log_string(message) if message is not None else None
    sanitized_kwargs = sanitize_log_mapping(data or {})

    detail_log = detail_logger.bind(job_id=job_id, **sanitized_kwargs)
    getattr(detail_log, level.lower())(event, message=sanitized_message)

    if event in root_summary_events:
        summary_log = root_logger.bind(job_id=job_id, **sanitized_kwargs)
        getattr(summary_log, level.lower())(event, message=sanitized_message)

    entry = ImportJobLog(
        import_job_id=job_id,
        logged_at=datetime.now(UTC),
        level=level.upper(),
        event=event,
        message=sanitized_message,
        data=sanitized_kwargs if sanitized_kwargs else {},
    )
    session.add(entry)
    return entry
