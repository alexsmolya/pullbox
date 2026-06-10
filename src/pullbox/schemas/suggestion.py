"""Matching suggestion request/response schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from pullbox.models.matching_suggestion import SuggestionStatus


class SuggestionResponse(BaseModel):
    """A matching suggestion returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    library_file_id: int
    parent_series_id: int | None = None
    suggested_comicvine_id: int | None = None
    suggested_title: str | None = None
    suggested_year: int | None = None
    suggested_publisher: str | None = None
    suggested_series_type: str = "standard"
    detection_source: str = "filename"
    confidence_score: float = 0.0
    reason: str | None = None
    status: SuggestionStatus = SuggestionStatus.PENDING

    # Enriched fields from relationships
    file_name: str | None = Field(None, description="Name of the unmatched file")
    parent_series_title: str | None = Field(None, description="Title of the parent series")

    created_at: datetime
    updated_at: datetime


class SuggestionAccept(BaseModel):
    """Request body for accepting a suggestion."""

    comicvine_id: int = Field(..., gt=0, description="ComicVine volume ID for the suggested series")
    library_root_id: int | None = Field(
        None,
        gt=0,
        description="Library root for the new series folder",
    )
