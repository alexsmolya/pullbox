"""Issue ORM model and related enums."""

from __future__ import annotations

import enum
from datetime import date  # noqa: TC003 - SQLAlchemy needs this at runtime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SQLAlchemyEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pullbox.models.base import Base, IdentityMixin, TimestampMixin

if TYPE_CHECKING:
    from pullbox.models.creator import Creator
    from pullbox.models.library import LibraryFile
    from pullbox.models.series import Series
    from pullbox.models.story_arc import StoryArc


class IssueType(enum.StrEnum):
    """Classification of comic format/type for naming templates."""

    ISSUE = "issue"
    ANNUAL = "annual"
    TPB = "tpb"
    OMNIBUS = "omnibus"
    GN = "gn"
    OGN = "ogn"
    HC = "hc"
    ONE_SHOT = "one_shot"
    SPECIAL = "special"
    DELUXE = "deluxe"
    COMPENDIUM = "compendium"
    VOLUME = "volume"

    @property
    def display_name(self) -> str:
        """Human-readable display name for use in naming templates."""
        return _ISSUE_TYPE_DISPLAY_NAMES[self]


_ISSUE_TYPE_DISPLAY_NAMES: dict[IssueType, str] = {
    IssueType.ISSUE: "",
    IssueType.ANNUAL: "Annual",
    IssueType.TPB: "TPB",
    IssueType.OMNIBUS: "Omnibus",
    IssueType.GN: "Graphic Novel",
    IssueType.OGN: "Original Graphic Novel",
    IssueType.HC: "Hardcover",
    IssueType.ONE_SHOT: "One Shot",
    IssueType.SPECIAL: "Special",
    IssueType.DELUXE: "Deluxe Edition",
    IssueType.COMPENDIUM: "Compendium",
    IssueType.VOLUME: "Volume",
}

_NON_STANDARD_ISSUE_TYPES: frozenset[IssueType] = frozenset(
    {
        IssueType.TPB,
        IssueType.OMNIBUS,
        IssueType.GN,
        IssueType.OGN,
        IssueType.HC,
        IssueType.ONE_SHOT,
        IssueType.SPECIAL,
        IssueType.DELUXE,
        IssueType.COMPENDIUM,
        IssueType.VOLUME,
    }
)


def is_non_standard_issue_type(issue_type: str | IssueType | None) -> bool:
    """Return True when an issue type should use the non-standard naming template."""
    if issue_type is None:
        return False
    if isinstance(issue_type, IssueType):
        return issue_type in _NON_STANDARD_ISSUE_TYPES
    try:
        return IssueType(issue_type) in _NON_STANDARD_ISSUE_TYPES
    except ValueError:
        return False


class IssueStatus(enum.StrEnum):
    UNKNOWN = "unknown"
    WANTED = "wanted"
    DOWNLOADING = "downloading"
    OWNED = "owned"
    SKIPPED = "skipped"


class Issue(Base, IdentityMixin, TimestampMixin):
    __tablename__ = "issues"
    __table_args__ = (
        UniqueConstraint("series_id", "issue_number", name="uq_series_issue"),
        Index("ix_issues_status", "status"),
        Index("ix_issues_release_date", "release_date"),
    )

    comicvine_id: Mapped[int | None] = mapped_column(unique=True, index=True)
    series_id: Mapped[int] = mapped_column(
        ForeignKey("series.id", ondelete="CASCADE"), nullable=False
    )
    issue_number: Mapped[float] = mapped_column(Float, nullable=False)
    title: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    release_date: Mapped[date | None] = mapped_column(Date)
    cover_path: Mapped[str | None] = mapped_column(String(500))
    cover_url: Mapped[str | None] = mapped_column(String(500))
    comicvine_url: Mapped[str | None] = mapped_column(String(500))

    # Type classification
    issue_type: Mapped[IssueType] = mapped_column(
        SQLAlchemyEnum(IssueType), default=IssueType.ISSUE
    )

    # Status tracking
    status: Mapped[IssueStatus] = mapped_column(
        SQLAlchemyEnum(IssueStatus), default=IssueStatus.SKIPPED
    )
    manual_skip: Mapped[bool] = mapped_column(default=False, server_default="0")

    # Metadata
    page_count: Mapped[int | None] = mapped_column(Integer)
    store_date: Mapped[date | None] = mapped_column(Date)
    metadata_source: Mapped[str | None] = mapped_column(String(50))

    # Integrity check (added by utilities sprint UT-F.1)
    integrity_status: Mapped[str | None] = mapped_column(Text, default="unchecked")
    integrity_checked_at: Mapped[str | None] = mapped_column(Text)
    integrity_details: Mapped[str | None] = mapped_column(Text, default="{}")

    # Relationships
    series: Mapped[Series] = relationship(back_populates="issues")
    library_file: Mapped[LibraryFile | None] = relationship(back_populates="issue", uselist=False)
    creators: Mapped[list[Creator]] = relationship(
        secondary="issue_creators", back_populates="issues"
    )
    story_arcs: Mapped[list[StoryArc]] = relationship(
        secondary="issue_story_arcs", back_populates="issues"
    )
