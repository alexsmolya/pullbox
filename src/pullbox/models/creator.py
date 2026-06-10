"""Creator ORM model and IssueCreator junction table."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pullbox.models.base import Base, IdentityMixin, TimestampMixin

if TYPE_CHECKING:
    from pullbox.models.issue import Issue


class Creator(Base, IdentityMixin, TimestampMixin):
    __tablename__ = "creators"

    comicvine_id: Mapped[int | None] = mapped_column(unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    comicvine_url: Mapped[str | None] = mapped_column(String(500))

    # Relationships
    issues: Mapped[list[Issue]] = relationship(
        secondary="issue_creators", back_populates="creators"
    )


class IssueCreator(Base):
    """Junction table: Issue <-> Creator with role."""

    __tablename__ = "issue_creators"

    issue_id: Mapped[int] = mapped_column(
        ForeignKey("issues.id", ondelete="CASCADE"), primary_key=True
    )
    creator_id: Mapped[int] = mapped_column(
        ForeignKey("creators.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(100))
