"""StoryArc ORM model and IssueStoryArc junction table."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pullbox.models.base import Base, IdentityMixin, TimestampMixin

if TYPE_CHECKING:
    from pullbox.models.issue import Issue


class StoryArc(Base, IdentityMixin, TimestampMixin):
    __tablename__ = "story_arcs"

    comicvine_id: Mapped[int | None] = mapped_column(unique=True, index=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    publisher_id: Mapped[int | None] = mapped_column(
        ForeignKey("publishers.id", ondelete="SET NULL")
    )
    comicvine_url: Mapped[str | None] = mapped_column(String(500))

    # Relationships
    issues: Mapped[list[Issue]] = relationship(
        secondary="issue_story_arcs", back_populates="story_arcs"
    )


class IssueStoryArc(Base):
    """Junction table: Issue <-> StoryArc with sequence."""

    __tablename__ = "issue_story_arcs"

    issue_id: Mapped[int] = mapped_column(
        ForeignKey("issues.id", ondelete="CASCADE"), primary_key=True
    )
    story_arc_id: Mapped[int] = mapped_column(
        ForeignKey("story_arcs.id", ondelete="CASCADE"), primary_key=True
    )
    sequence_number: Mapped[int | None] = mapped_column(Integer)
