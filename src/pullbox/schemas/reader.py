"""Internal web-reader API response contracts."""

from datetime import datetime

from pydantic import BaseModel, Field

from pullbox.models.library import FileFormat


class ReaderManifestResponse(BaseModel):
    """Thin manifest consumed by the embedded web reader."""

    issue_id: int
    title: str
    issue_label: str
    format: FileFormat
    page_count: int
    revision: str
    initial_page_index: int = 0
    page_url_template: str
    progress_url: str


class ReaderProgressUpdate(BaseModel):
    """Explicit settled-page state sent independently from page requests."""

    revision: str = Field(min_length=1, max_length=64)
    page_index: int = Field(ge=0)
    page_count: int = Field(ge=1)
    completion_candidate: bool = False


class ReaderProgressResponse(BaseModel):
    """Persisted private reader state returned to the embedded client."""

    page_index: int
    page_count: int
    revision: str
    completed_at: datetime | None
    updated_at: datetime


class ReaderFormatCapabilityResponse(BaseModel):
    """Runtime readiness for one supported reader format."""

    format: FileFormat
    available: bool
    detail: str


class ReaderCacheDiagnosticsResponse(BaseModel):
    """Path-free bounded reader cache diagnostics."""

    cache_file_count: int
    cache_bytes: int
    max_cache_bytes: int
    open_source_count: int
    max_open_sources: int
    max_workers: int


class ReaderCapabilitiesResponse(BaseModel):
    """Private reader capability and cache report."""

    enabled: bool
    formats: list[ReaderFormatCapabilityResponse]
    cache: ReaderCacheDiagnosticsResponse


class ReaderCacheClearResponse(BaseModel):
    """Generated cache cleanup result."""

    files_removed: int
    bytes_removed: int
