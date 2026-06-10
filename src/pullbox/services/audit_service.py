"""Audit logging service — records security-relevant events."""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import TYPE_CHECKING

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.exc import OperationalError

from pullbox.core.log_deduper import log_deduped_warning
from pullbox.core.log_sanitizer import sanitize_log_mapping, sanitize_log_string
from pullbox.models.audit_log import AuditEventType, AuditLog

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession
    from starlette.requests import Request

# Set of in-flight audit tasks — prevents GC from collecting fire-and-forget tasks
_background_tasks: set[asyncio.Task[None]] = set()

_AUDIT_LOCK_RETRY_ATTEMPTS = 5


def _is_locked_error(exc: BaseException) -> bool:
    """Return True when SQLite reports a transient lock."""
    message = str(exc).lower()
    return "database is locked" in message or "locking protocol" in message


class AuditService:
    """Records and queries security audit log events."""

    @staticmethod
    async def log_event(
        session: AsyncSession,
        event_type: AuditEventType,
        *,
        source_ip: str | None = None,
        user_id: int | None = None,
        username: str | None = None,
        detail: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> AuditLog:
        """Record a security event in the audit log.

        IMPORTANT: The detail and metadata fields must NEVER contain secrets,
        passwords, API keys, or tokens. Only record what happened, not
        sensitive data involved.
        """
        sanitized_detail = sanitize_log_string(detail) if detail is not None else None
        sanitized_metadata = sanitize_log_mapping(metadata or {}) if metadata else None
        entry = AuditLog(
            event_type=event_type.value,
            source_ip=source_ip,
            user_id=user_id,
            username=username,
            detail=sanitized_detail,
            metadata_json=json.dumps(sanitized_metadata) if sanitized_metadata else None,
        )
        session.add(entry)
        await session.flush()
        return entry

    @staticmethod
    async def get_events(
        session: AsyncSession,
        *,
        event_type: AuditEventType | None = None,
        user_id: int | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[AuditLog], int]:
        """Query audit log events with optional filters.

        Returns (events, total_count) for pagination.
        """
        conditions: list[ColumnElement[bool]] = []
        if event_type is not None:
            conditions.append(AuditLog.event_type == event_type.value)
        if user_id is not None:
            conditions.append(AuditLog.user_id == user_id)
        if since is not None:
            conditions.append(AuditLog.timestamp >= since)
        if until is not None:
            conditions.append(AuditLog.timestamp <= until)

        # Total count
        count_stmt = select(func.count(AuditLog.id)).where(*conditions)
        total = (await session.execute(count_stmt)).scalar_one()

        # Paginated results
        query = (
            select(AuditLog)
            .where(*conditions)
            .order_by(AuditLog.timestamp.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(query)
        events = list(result.scalars().all())

        return events, total

    @staticmethod
    async def get_event_counts_by_type(
        session: AsyncSession,
        *,
        since: datetime | None = None,
    ) -> dict[AuditEventType, int]:
        """Get event counts grouped by type for the summary panel."""
        conditions: list[ColumnElement[bool]] = []
        if since is not None:
            conditions.append(AuditLog.timestamp >= since)

        stmt = (
            select(AuditLog.event_type, func.count(AuditLog.id))
            .where(*conditions)
            .group_by(AuditLog.event_type)
        )
        result = await session.execute(stmt)
        counts: dict[AuditEventType, int] = {}
        for event_type_value, count in result.all():
            with contextlib.suppress(ValueError):
                counts[AuditEventType(event_type_value)] = count
        return counts


def source_ip_from_request(request: Request | None) -> str | None:
    """Return the client IP value used for audit records."""
    return request.client.host if request is not None and request.client else None


async def record_audit_event(
    session: AsyncSession,
    event_type: AuditEventType,
    *,
    use_dedicated_session: bool = True,
    source_ip: str | None = None,
    user_id: int | None = None,
    username: str | None = None,
    detail: str | None = None,
    metadata: dict[str, object] | None = None,
) -> None:
    """Best-effort audit log for request handlers.

    Production requests use a dedicated session by default so audit writes
    never poison the primary request transaction under SQLite lock pressure.
    During tests, dedicated writes fall back to the request session so
    assertions can inspect persisted audit rows deterministically.
    """
    import os

    import structlog

    logger = structlog.get_logger(__name__)
    used_request_session = False
    try:
        if use_dedicated_session and not os.environ.get("PYTEST_CURRENT_TEST"):
            await audit_event(
                event_type,
                source_ip=source_ip,
                user_id=user_id,
                username=username,
                detail=detail,
                metadata=metadata,
            )
            return

        used_request_session = True
        await AuditService.log_event(
            session,
            event_type,
            source_ip=source_ip,
            user_id=user_id,
            username=username,
            detail=detail,
            metadata=metadata,
        )
    except Exception:
        if used_request_session:
            with contextlib.suppress(Exception):
                await session.rollback()
        logger.warning("audit_log_failure", event_type=event_type.value)


async def audit_event(
    event_type: AuditEventType,
    *,
    source_ip: str | None = None,
    user_id: int | None = None,
    username: str | None = None,
    detail: str | None = None,
    metadata: dict[str, object] | None = None,
) -> None:
    """Best-effort audit log using a dedicated session.

    Uses its own session + commit so entries survive request rollbacks
    (e.g., on login failure or rate limiting). Safe to call from anywhere.

    Skips writing during test runs (PULLBOX_SECRET_KEY=test-ci-key or
    pytest detected) to prevent test data from polluting the dev database.
    """
    import os

    import structlog

    from pullbox.database import get_session_factory

    logger = structlog.get_logger(__name__)

    # Don't write audit events during test runs — the dedicated session
    # bypasses the test DB override and writes to the real dev database
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return

    async def _write() -> None:
        factory = get_session_factory()
        for attempt in range(_AUDIT_LOCK_RETRY_ATTEMPTS):
            async with factory() as session:
                try:
                    await AuditService.log_event(
                        session,
                        event_type,
                        source_ip=source_ip,
                        user_id=user_id,
                        username=username,
                        detail=detail,
                        metadata=metadata,
                    )
                    await session.commit()
                    return
                except OperationalError as exc:
                    await session.rollback()
                    if _is_locked_error(exc) and attempt < (_AUDIT_LOCK_RETRY_ATTEMPTS - 1):
                        await asyncio.sleep(0.25 * (attempt + 1))
                        continue
                    if _is_locked_error(exc):
                        log_deduped_warning(
                            logger,
                            "audit_log_skipped_locked",
                            key=("audit_log_skipped_locked", event_type.value),
                            event_type=event_type.value,
                            window_seconds=300.0,
                        )
                        return
                    logger.warning("audit_log_failure", event_type=event_type.value)
                    return
                except Exception:
                    await session.rollback()
                    logger.warning("audit_log_failure", event_type=event_type.value)
                    return

    # Fire and forget — don't block the request on audit writes
    task = asyncio.create_task(_write())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
