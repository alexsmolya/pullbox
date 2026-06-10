"""Download request/response schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from pullbox.models.download import DownloadClientType, DownloadState


class DownloadRequest(BaseModel):
    """Request body for triggering a download of a specific release."""

    download_url: str = Field(..., min_length=1, description="NZB/torrent URL to download")
    title: str = Field(..., min_length=1, description="Release title")
    indexer_id: int | None = Field(None, gt=0, description="Indexer that provided the release")


class DownloadQueueItem(BaseModel):
    """Active download in the queue."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    issue_id: int
    title: str
    state: DownloadState
    download_client: DownloadClientType
    external_id: str | None = None
    file_size: int | None = Field(None, description="File size in bytes")
    sent_at: datetime | None = None
    series_title: str | None = Field(None, description="Parent series title")
    issue_number: float | None = Field(None, description="Issue number")


class DownloadHistoryItem(BaseModel):
    """Completed download in history."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    issue_id: int
    title: str
    state: DownloadState
    download_client: DownloadClientType
    file_size: int | None = None
    error_message: str | None = None
    sent_at: datetime | None = None
    completed_at: datetime | None = None
    imported_at: datetime | None = None
    series_title: str | None = Field(None, description="Parent series title")
    issue_number: float | None = Field(None, description="Issue number")
    created_at: datetime
