"""Pydantic schemas for audit log API responses."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - Pydantic needs this at runtime

from pydantic import BaseModel


class AuditLogEntry(BaseModel):
    """Single audit log event for API responses."""

    model_config = {"from_attributes": True}

    id: int
    event_type: str
    timestamp: datetime
    source_ip: str | None
    user_id: int | None
    username: str | None
    detail: str | None


class AuditLogResponse(BaseModel):
    """Paginated audit log response."""

    events: list[AuditLogEntry]
    total: int
    page: int
    total_pages: int
