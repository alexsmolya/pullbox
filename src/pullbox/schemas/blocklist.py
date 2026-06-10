"""Pydantic schemas for blocklist API requests and responses."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003

from pydantic import BaseModel, ConfigDict, Field

from pullbox.models.blocklist import BlocklistReason


class BlocklistAddRequest(BaseModel):
    """Request body for manually adding a release to the blocklist."""

    release_title: str = Field(..., min_length=1, max_length=500, description="Release title")
    reason: BlocklistReason = Field(BlocklistReason.MANUAL, description="Why this was blocklisted")
    download_url: str | None = Field(None, max_length=2000, description="Download URL")
    series_id: int | None = Field(None, gt=0, description="Associated series ID")
    issue_id: int | None = Field(None, gt=0, description="Associated issue ID")


class BlocklistBulkDeleteRequest(BaseModel):
    """Request body for bulk-deleting blocklist entries."""

    ids: list[int] = Field(..., min_length=1, max_length=100, description="Entry IDs to remove")


class BlocklistEntryResponse(BaseModel):
    """Blocklist entry returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    release_title: str
    release_title_normalized: str
    download_url: str | None = None
    series_id: int | None = None
    issue_id: int | None = None
    indexer_id: int | None = None
    reason: BlocklistReason
    error_message: str | None = None
    release_group: str | None = None
    download_history_id: int | None = None
    series_title: str | None = Field(None, description="Denormalized series name")
    created_at: datetime
    updated_at: datetime


class BlocklistListResponse(BaseModel):
    """Paginated blocklist list response."""

    entries: list[BlocklistEntryResponse]
    total: int
    page: int
    page_size: int


class BlocklistCountResponse(BaseModel):
    """Blocklist entry count."""

    count: int


class BlocklistBulkDeleteResponse(BaseModel):
    """Result of a bulk delete operation."""

    removed: int


class ReleaseGroupListRequest(BaseModel):
    """Request body for updating the release group blocklist."""

    groups: list[str] = Field(..., description="List of release group names to block")


class ReleaseGroupListResponse(BaseModel):
    """Current release group blocklist."""

    groups: list[str]
