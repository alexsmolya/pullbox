"""Audit log API routes — query security event history."""

from __future__ import annotations

import math
from datetime import datetime  # noqa: TC003 - FastAPI needs this at runtime

import structlog
from fastapi import APIRouter, Query

from pullbox.api.deps import DbSession, InteractiveOperatorUser  # noqa: TC001
from pullbox.models.audit_log import AuditEventType
from pullbox.services.audit_service import AuditService

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["audit"], include_in_schema=False)


@router.get("/audit/events")
async def list_audit_events(
    user: InteractiveOperatorUser,
    session: DbSession,
    event_type: str | None = Query(default=None, description="Filter by event type"),
    since: datetime | None = Query(default=None, description="Events after this time"),  # noqa: B008
    until: datetime | None = Query(default=None, description="Events before this time"),  # noqa: B008
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(default=50, ge=1, le=200, description="Events per page"),
) -> dict[str, object]:
    """List audit log events with optional filters. Admin only."""
    from pullbox.schemas.audit import AuditLogEntry, AuditLogResponse

    parsed_type: AuditEventType | None = None
    if event_type:
        try:
            parsed_type = AuditEventType(event_type)
        except ValueError:
            parsed_type = None

    offset = (page - 1) * per_page
    events, total = await AuditService.get_events(
        session,
        event_type=parsed_type,
        since=since,
        until=until,
        limit=per_page,
        offset=offset,
    )

    total_pages = max(1, math.ceil(total / per_page))

    result = AuditLogResponse(
        events=[AuditLogEntry.model_validate(e) for e in events],
        total=total,
        page=page,
        total_pages=total_pages,
    )
    return result.model_dump(mode="json")
