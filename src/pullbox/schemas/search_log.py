"""Search log response schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from pullbox.models.search_log import SearchType


class SearchLogItem(BaseModel):
    """A single search log entry for display."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    issue_id: int
    series_title: str
    issue_number: float
    search_type: SearchType
    results_found: int = Field(0, description="Raw indexer hits")
    results_grabbed: int = Field(0, description="Auto-grabbed count")
    results_queued: int = Field(0, description="Sent to intervention queue")
    results_rejected: int = Field(0, description="Below threshold")
    details: dict[str, object] = Field(default_factory=dict)
    best_confidence: str | None = None
    created_at: datetime
