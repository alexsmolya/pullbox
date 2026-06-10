"""Dashboard intelligence rollup models."""

from __future__ import annotations

from datetime import date, datetime  # noqa: TC003 - SQLAlchemy needs runtime types

from sqlalchemy import JSON, BigInteger, Date, Float, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from pullbox.models.base import Base, IdentityMixin, TimestampMixin, UTCDateTime


class DashboardMetricRollup(Base, IdentityMixin, TimestampMixin):
    """Hourly dashboard metric rollup used for trend and delta calculations."""

    __tablename__ = "dashboard_metric_rollups"
    __table_args__ = (
        UniqueConstraint("metric_key", "bucket_start", name="uq_dashboard_metric_rollups_key"),
        Index("ix_dashboard_metric_rollups_metric_bucket", "metric_key", "bucket_start"),
    )

    metric_key: Mapped[str] = mapped_column(String(100), nullable=False)
    bucket_start: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    bucket_end: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    context_json: Mapped[dict] = mapped_column(  # type: ignore[type-arg]
        JSON,
        default=dict,
        server_default="{}",
        nullable=False,
    )


class DashboardStorageSnapshot(Base, IdentityMixin, TimestampMixin):
    """Daily disk-usage snapshot for storage runway projections."""

    __tablename__ = "dashboard_storage_snapshots"
    __table_args__ = (
        UniqueConstraint("snapshot_date", name="uq_dashboard_storage_snapshots_date"),
        Index("ix_dashboard_storage_snapshots_snapshot_date", "snapshot_date"),
    )

    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    total_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    used_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    free_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    used_percent: Mapped[float] = mapped_column(Float, nullable=False)
