"""Local cache models for upstream What's New release payloads."""

from __future__ import annotations

import enum
from datetime import date, datetime  # noqa: TC003 - SQLAlchemy needs runtime types
from typing import Any

from sqlalchemy import JSON, Date, Index, String, UniqueConstraint
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy.orm import Mapped, mapped_column

from pullbox.models.base import Base, IdentityMixin, TimestampMixin, UTCDateTime


class WhatsNewCacheKind(enum.StrEnum):
    """Types of upstream release payloads stored in the local cache."""

    CURRENT_WEEK = "current_week"
    UPCOMING = "upcoming"


class WhatsNewReleaseCache(Base, IdentityMixin, TimestampMixin):
    """Cached pullbox-data release payload plus local freshness metadata."""

    __tablename__ = "whats_new_release_cache"
    __table_args__ = (
        UniqueConstraint("cache_key", name="uq_whats_new_release_cache_key"),
        Index("ix_whats_new_release_cache_kind", "cache_kind"),
        Index("ix_whats_new_release_cache_fetched_at", "fetched_at"),
        Index("ix_whats_new_release_cache_last_success", "last_successful_refresh_at"),
    )

    cache_key: Mapped[str] = mapped_column(String(255), nullable=False)
    cache_kind: Mapped[WhatsNewCacheKind] = mapped_column(
        SQLAlchemyEnum(WhatsNewCacheKind), nullable=False
    )
    store_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    publisher: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    last_successful_refresh_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
