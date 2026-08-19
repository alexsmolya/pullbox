"""Private per-user embedded-reader resume and completion state."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - SQLAlchemy needs this at runtime

from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from pullbox.models.base import Base, IdentityMixin, TimestampMixin, UTCDateTime


class IssueReaderState(Base, IdentityMixin, TimestampMixin):
    """Private reader state, intentionally separate from acquisition status."""

    __tablename__ = "issue_reader_states"
    __table_args__ = (
        UniqueConstraint("user_id", "issue_id", name="uq_issue_reader_state_user_issue"),
        Index("ix_issue_reader_states_issue", "issue_id"),
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    issue_id: Mapped[int] = mapped_column(
        ForeignKey("issues.id", ondelete="CASCADE"), nullable=False
    )
    last_page_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_revision: Mapped[str] = mapped_column(String(64), nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
