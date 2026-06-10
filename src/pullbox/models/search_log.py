"""SearchLog ORM model — records search operations for user visibility.

Tracks each search attempt (automated, manual, bulk) with result counts
so users can see what searches ran, how many results were found, and what
actions were taken (grabbed, queued, rejected).
"""

from __future__ import annotations

import enum
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy import (
    Enum as SQLAlchemyEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pullbox.models.base import Base, IdentityMixin, TimestampMixin

if TYPE_CHECKING:
    from pullbox.models.issue import Issue


class SearchType(enum.StrEnum):
    """Type of search that produced this log entry."""

    MANUAL = "manual"
    AUTOMATED = "automated"
    BULK = "bulk"


class SearchLog(Base, IdentityMixin, TimestampMixin):
    """A record of a single search operation for an issue."""

    __tablename__ = "search_logs"
    __table_args__ = (
        Index("ix_search_logs_created", "created_at"),
        Index("ix_search_logs_type", "search_type"),
    )

    issue_id: Mapped[int] = mapped_column(
        ForeignKey("issues.id", ondelete="CASCADE"), nullable=False
    )

    # Denormalized for display without joins
    series_title: Mapped[str] = mapped_column(String(500), nullable=False)
    issue_number: Mapped[float] = mapped_column(Float, nullable=False)

    search_type: Mapped[SearchType] = mapped_column(SQLAlchemyEnum(SearchType), nullable=False)

    # Result counters
    results_found: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    results_grabbed: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    results_queued: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    results_rejected: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    results_blocklisted: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    # Diagnostic detail
    details: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")  # type: ignore[type-arg]
    best_confidence: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Relationships
    issue: Mapped[Issue] = relationship()
