"""Indexer configuration ORM model."""

import enum
from datetime import datetime

from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from pullbox.models.base import Base, IdentityMixin, TimestampMixin, UTCDateTime


class IndexerType(enum.StrEnum):
    NEWZNAB = "newznab"
    TORZNAB = "torznab"
    PROWLARR = "prowlarr"


class IndexerSource(enum.StrEnum):
    """Where the indexer configuration originated."""

    MANUAL = "manual"
    PROWLARR = "prowlarr"


class IndexerConfig(Base, IdentityMixin, TimestampMixin):
    __tablename__ = "indexer_configs"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    indexer_type: Mapped[IndexerType] = mapped_column(SQLAlchemyEnum(IndexerType))
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    api_key: Mapped[str] = mapped_column(String(1024), nullable=False)  # encrypted at rest
    enabled: Mapped[bool] = mapped_column(default=True)
    priority: Mapped[int] = mapped_column(Integer, default=50)
    categories: Mapped[str | None] = mapped_column(String(255))

    # Prowlarr sync tracking
    source: Mapped[str] = mapped_column(String(20), default="manual")
    prowlarr_indexer_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Search capability flags (Prowlarr sync profiles)
    enable_rss: Mapped[bool] = mapped_column(default=True)
    enable_automatic_search: Mapped[bool] = mapped_column(default=True)
    enable_interactive_search: Mapped[bool] = mapped_column(default=True)
    resolver_enabled: Mapped[bool] = mapped_column(
        default=False,
        server_default="0",
        nullable=False,
    )

    # Health tracking
    last_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_failure_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    disabled_until: Mapped[datetime | None] = mapped_column(UTCDateTime)

    # Capabilities (cached from indexer)
    capabilities_json: Mapped[str | None] = mapped_column(Text)
