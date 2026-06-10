"""PendingMatch ORM model — stores ambiguous search matches for user review.

When a search finds a release that matches with medium or low confidence,
the result is stored as a PendingMatch for the user to approve or reject
via the intervention queue UI.
"""

from __future__ import annotations

import enum
from datetime import datetime  # noqa: TC003 - SQLAlchemy needs this at runtime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pullbox.models.base import Base, IdentityMixin, TimestampMixin, UTCDateTime

if TYPE_CHECKING:
    from pullbox.models.indexer import IndexerConfig
    from pullbox.models.issue import Issue


class PendingMatchStatus(enum.StrEnum):
    """Status of a pending match in the intervention queue."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class PendingMatch(Base, IdentityMixin, TimestampMixin):
    """A search result held for user review before downloading."""

    __tablename__ = "pending_matches"
    __table_args__ = (
        UniqueConstraint("issue_id", "download_url", name="uq_pending_issue_url"),
        Index("ix_pending_status", "status"),
        Index("ix_pending_issue", "issue_id"),
        Index("ix_pending_created", "created_at"),
    )

    issue_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("issues.id", ondelete="CASCADE"), nullable=False
    )
    release_title: Mapped[str] = mapped_column(String(500), nullable=False)
    download_url: Mapped[str] = mapped_column(Text, nullable=False)
    indexer_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("indexer_configs.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_torrent: Mapped[bool] = mapped_column(Boolean, default=False)
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    confidence: Mapped[str] = mapped_column(String(20), nullable=False)
    match_details: Mapped[dict] = mapped_column(JSON, default=dict)  # type: ignore[type-arg]
    status: Mapped[str] = mapped_column(
        String(20), default=PendingMatchStatus.PENDING, nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Relationships
    issue: Mapped[Issue] = relationship(lazy="joined")
    indexer: Mapped[IndexerConfig | None] = relationship(lazy="joined")
