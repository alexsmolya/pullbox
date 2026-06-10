"""Persistent metadata-provider response cache models."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - SQLAlchemy needs runtime types
from typing import Any

from sqlalchemy import JSON, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from pullbox.models.base import Base, IdentityMixin, TimestampMixin, UTCDateTime


class MetadataProviderCacheEntry(Base, IdentityMixin, TimestampMixin):
    """Cached upstream metadata response with local freshness metadata."""

    __tablename__ = "metadata_provider_cache"
    __table_args__ = (
        UniqueConstraint(
            "provider_name",
            "cache_kind",
            "cache_key",
            name="uq_metadata_provider_cache_identity",
        ),
        Index("ix_metadata_provider_cache_provider_kind", "provider_name", "cache_kind"),
        Index("ix_metadata_provider_cache_expires_at", "expires_at"),
        Index("ix_metadata_provider_cache_fetched_at", "fetched_at"),
    )

    provider_name: Mapped[str] = mapped_column(String(50), nullable=False)
    cache_kind: Mapped[str] = mapped_column(String(80), nullable=False)
    cache_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
