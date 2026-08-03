"""Intervention queue request/response schemas."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - Pydantic needs this at runtime

from pydantic import BaseModel, ConfigDict, Field


class IssueContext(BaseModel):
    """Nested issue info within a pending match response."""

    id: int
    series_title: str | None = None
    issue_number: float
    issue_type: str | None = None


class PendingMatchResponse(BaseModel):
    """A pending match returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    issue: IssueContext
    release_title: str
    download_url: str
    file_size: int | None = None
    confidence: str
    match_details: dict[str, object] = Field(default_factory=dict)
    is_torrent: bool = False
    status: str
    created_at: datetime
    resolved_at: datetime | None = None
    resolved_by: str | None = None


class PendingMatchListResponse(BaseModel):
    """Paginated list of pending matches."""

    items: list[PendingMatchResponse]
    total: int
    page: int
    pages: int


class PendingMatchCountResponse(BaseModel):
    """Count of pending matches."""

    count: int


class RejectRequest(BaseModel):
    """Request body for rejecting a pending match."""

    reason: str | None = Field(None, description="Optional rejection reason")


class ApproveResponse(BaseModel):
    """Response after approving a pending match."""

    download_id: int | None = None
    acquisition_id: int | None = None
    issue_id: int
    title: str
    status: str
    source_kind: str = "indexer"


class BulkActionRequest(BaseModel):
    """Request body for bulk approve/reject."""

    ids: list[int] = Field(..., min_length=1, max_length=100)
    reason: str | None = Field(None, description="Optional reason (reject only)")


class BulkActionResult(BaseModel):
    """Result for a single item in a bulk operation."""

    id: int
    success: bool
    error: str | None = None


class BulkActionResponse(BaseModel):
    """Response for bulk approve/reject operations."""

    processed: int
    succeeded: int
    failed: int
    results: list[BulkActionResult]
