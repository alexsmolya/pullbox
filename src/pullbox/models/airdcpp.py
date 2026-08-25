"""AirDC++-specific persistence models."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - SQLAlchemy needs this at runtime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, CheckConstraint, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pullbox.models.base import Base, IdentityMixin, TimestampMixin, UTCDateTime

if TYPE_CHECKING:
    from pullbox.models.client import DownloadClientConfig


class AirDcppClientSettings(Base, IdentityMixin, TimestampMixin):
    """Bounded AirDC++ settings owned by one download-client configuration."""

    __tablename__ = "airdcpp_client_settings"
    __table_args__ = (
        UniqueConstraint("client_config_id", name="uq_airdcpp_settings_client_config"),
        CheckConstraint(
            "minimum_search_interval_seconds BETWEEN 45 AND 3600",
            name="ck_airdcpp_settings_minimum_search_interval",
        ),
        CheckConstraint(
            "manual_collection_seconds BETWEEN 1 AND 120",
            name="ck_airdcpp_settings_manual_collection",
        ),
        CheckConstraint(
            "automatic_collection_seconds BETWEEN 1 AND 120",
            name="ck_airdcpp_settings_automatic_collection",
        ),
        CheckConstraint(
            "max_results BETWEEN 1 AND 1000",
            name="ck_airdcpp_settings_max_results",
        ),
        CheckConstraint(
            "max_retained_routes BETWEEN max_results AND 2000",
            name="ck_airdcpp_settings_retained_routes",
        ),
        CheckConstraint(
            "max_concurrent_searches BETWEEN 1 AND 4",
            name="ck_airdcpp_settings_concurrent_searches",
        ),
        CheckConstraint(
            "request_timeout_seconds BETWEEN 1 AND 120",
            name="ck_airdcpp_settings_request_timeout",
        ),
        CheckConstraint(
            "search_dispatch_deadline_seconds BETWEEN 5 AND 300",
            name="ck_airdcpp_settings_dispatch_deadline",
        ),
        CheckConstraint(
            "reconciliation_interval_seconds BETWEEN 10 AND 300",
            name="ck_airdcpp_settings_reconciliation_interval",
        ),
        CheckConstraint(
            "queue_priority IS NULL OR queue_priority BETWEEN -1 AND 6",
            name="ck_airdcpp_settings_queue_priority",
        ),
    )

    client_config_id: Mapped[int] = mapped_column(
        ForeignKey("download_client_configs.id", ondelete="CASCADE"),
        nullable=False,
    )
    search_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="1",
        nullable=False,
    )
    automatic_search_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="0",
        nullable=False,
    )
    minimum_search_interval_seconds: Mapped[int] = mapped_column(
        Integer,
        default=45,
        server_default="45",
        nullable=False,
    )
    manual_collection_seconds: Mapped[int] = mapped_column(
        Integer,
        default=8,
        server_default="8",
        nullable=False,
    )
    automatic_collection_seconds: Mapped[int] = mapped_column(
        Integer,
        default=15,
        server_default="15",
        nullable=False,
    )
    max_results: Mapped[int] = mapped_column(
        Integer,
        default=200,
        server_default="200",
        nullable=False,
    )
    max_retained_routes: Mapped[int] = mapped_column(
        Integer,
        default=400,
        server_default="400",
        nullable=False,
    )
    max_concurrent_searches: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default="1",
        nullable=False,
    )
    request_timeout_seconds: Mapped[int] = mapped_column(
        Integer,
        default=15,
        server_default="15",
        nullable=False,
    )
    search_dispatch_deadline_seconds: Mapped[int] = mapped_column(
        Integer,
        default=45,
        server_default="45",
        nullable=False,
    )
    reconciliation_interval_seconds: Mapped[int] = mapped_column(
        Integer,
        default=30,
        server_default="30",
        nullable=False,
    )
    hub_allowlist: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
        server_default="[]",
        nullable=False,
    )
    queue_priority: Mapped[int | None] = mapped_column(Integer)
    next_search_allowed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    client_config: Mapped[DownloadClientConfig] = relationship(back_populates="airdcpp_settings")
