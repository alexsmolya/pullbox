"""Download history ORM model and related enums."""

from __future__ import annotations

import enum
from datetime import datetime  # noqa: TC003 - SQLAlchemy needs this at runtime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy import (
    Enum as SQLAlchemyEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pullbox.models.base import Base, IdentityMixin, TimestampMixin, UTCDateTime

if TYPE_CHECKING:
    from pullbox.models.indexer import IndexerConfig
    from pullbox.models.issue import Issue


class DownloadState(enum.StrEnum):
    QUEUED = "queued"
    SENT = "sent"
    DOWNLOADING = "downloading"
    FINALIZING = "finalizing"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRY_PENDING = "retry_pending"
    # DEPRECATED: kept for DB compatibility only. Application code no longer
    # sets these states.  Use imported_at timestamp to determine import status.
    POST_PROCESSING = "post_processing"
    IMPORTED = "imported"


class DownloadClientType(enum.StrEnum):
    SABNZBD = "sabnzbd"
    NZBGET = "nzbget"
    QBITTORRENT = "qbittorrent"
    TRANSMISSION = "transmission"
    DELUGE = "deluge"
    # DDL types added in Sprint 9

    @property
    def is_usenet(self) -> bool:
        return self in {DownloadClientType.SABNZBD, DownloadClientType.NZBGET}

    @property
    def is_torrent(self) -> bool:
        return self in {
            DownloadClientType.QBITTORRENT,
            DownloadClientType.TRANSMISSION,
            DownloadClientType.DELUGE,
        }


class DownloadHistory(Base, IdentityMixin, TimestampMixin):
    __tablename__ = "download_history"
    __table_args__ = (
        Index("ix_download_history_state", "state"),
        Index("ix_download_history_issue", "issue_id"),
    )

    issue_id: Mapped[int] = mapped_column(
        ForeignKey("issues.id", ondelete="CASCADE"), nullable=False
    )
    indexer_id: Mapped[int | None] = mapped_column(
        ForeignKey("indexer_configs.id", ondelete="SET NULL")
    )

    # Download details
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    download_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    download_client: Mapped[DownloadClientType] = mapped_column(SQLAlchemyEnum(DownloadClientType))
    external_id: Mapped[str | None] = mapped_column(String(255))
    state: Mapped[DownloadState] = mapped_column(
        SQLAlchemyEnum(DownloadState), default=DownloadState.QUEUED
    )

    # Result details
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    downloaded_path: Mapped[str | None] = mapped_column(String(1000))
    final_path: Mapped[str | None] = mapped_column(String(1000))
    error_message: Mapped[str | None] = mapped_column(Text)

    # Retry
    retry_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    max_retries: Mapped[int] = mapped_column(Integer, default=3, server_default="3")
    next_retry_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    # Timing
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    imported_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    # Relationships
    issue: Mapped[Issue] = relationship()
    indexer: Mapped[IndexerConfig | None] = relationship()
