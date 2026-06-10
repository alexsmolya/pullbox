"""Blocklist ORM model — tracks releases that should not be re-downloaded."""

from __future__ import annotations

import enum
from typing import TYPE_CHECKING

from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy import (
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pullbox.models.base import Base, IdentityMixin, TimestampMixin

if TYPE_CHECKING:
    from pullbox.models.indexer import IndexerConfig
    from pullbox.models.issue import Issue
    from pullbox.models.series import Series


class BlocklistReason(enum.StrEnum):
    """Why a release was blocklisted."""

    FAILED = "failed"
    REJECTED = "rejected"
    MANUAL = "manual"


def normalize_release_title(title: str) -> str:
    """Normalize a release title for blocklist matching.

    Lowercases, strips, and collapses whitespace so that titles differing
    only in case or spacing are treated as the same release.
    """
    return " ".join(title.lower().split())


class BlocklistEntry(Base, IdentityMixin, TimestampMixin):
    """A release that should not be re-downloaded.

    Entries are matched by normalized title (case-insensitive, whitespace-collapsed).
    They can be auto-added on download failure, on intervention rejection, or manually.
    """

    __tablename__ = "blocklist_entries"
    __table_args__ = (
        Index("ix_blocklist_title_norm", "release_title_normalized", unique=True),
        Index("ix_blocklist_series", "series_id"),
        Index("ix_blocklist_reason", "reason"),
        Index("ix_blocklist_created", "created_at"),
    )

    release_title: Mapped[str] = mapped_column(String(500), nullable=False)
    release_title_normalized: Mapped[str] = mapped_column(String(500), nullable=False)
    download_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    series_id: Mapped[int | None] = mapped_column(
        ForeignKey("series.id", ondelete="CASCADE"), nullable=True
    )
    issue_id: Mapped[int | None] = mapped_column(
        ForeignKey("issues.id", ondelete="CASCADE"), nullable=True
    )
    indexer_id: Mapped[int | None] = mapped_column(
        ForeignKey("indexer_configs.id", ondelete="CASCADE"), nullable=True
    )
    reason: Mapped[BlocklistReason] = mapped_column(SQLAlchemyEnum(BlocklistReason), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    release_group: Mapped[str | None] = mapped_column(String(100), nullable=True)
    download_history_id: Mapped[int | None] = mapped_column(
        ForeignKey("download_history.id", ondelete="SET NULL"), nullable=True
    )

    series: Mapped[Series | None] = relationship()
    issue: Mapped[Issue | None] = relationship()
    indexer: Mapped[IndexerConfig | None] = relationship()
