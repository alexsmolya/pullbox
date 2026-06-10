"""Generic pagination wrapper for list endpoints."""

from pydantic import BaseModel, Field


class PaginatedResponse[T](BaseModel):
    """Paginated list response envelope."""

    items: list[T] = Field(description="Page of results")
    total: int = Field(description="Total number of matching records")
    limit: int = Field(description="Maximum items per page")
    offset: int = Field(description="Number of items skipped")
    has_more: bool = Field(description="Whether more items exist beyond this page")
