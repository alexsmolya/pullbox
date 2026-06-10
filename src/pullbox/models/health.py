"""Health check ORM model."""

import enum
from datetime import datetime

from sqlalchemy import Boolean, Float, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy.orm import Mapped, mapped_column

from pullbox.models.base import Base, IdentityMixin, TimestampMixin, UTCDateTime


class HealthStatus(enum.StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class HealthCheckResult(Base, IdentityMixin):
    __tablename__ = "health_check_results"
    __table_args__ = (
        Index("ix_health_check_component_time", "component", "checked_at"),
        Index(
            "ix_health_check_component_summary_time",
            "component",
            "is_summary",
            "checked_at",
        ),
        Index("ix_health_check_component_run", "component", "run_id"),
        Index(
            "ix_health_check_component_subject_summary_time",
            "component",
            "subject_key",
            "is_summary",
            "checked_at",
        ),
        Index(
            "ix_health_check_component_subject_run",
            "component",
            "subject_key",
            "run_id",
        ),
    )

    component: Mapped[str] = mapped_column(String(100), nullable=False)
    check_name: Mapped[str] = mapped_column(String(100), nullable=False)
    subject_key: Mapped[str | None] = mapped_column(String(100))
    subject_label: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[HealthStatus] = mapped_column(SQLAlchemyEnum(HealthStatus))
    message: Mapped[str | None] = mapped_column(Text)
    details_json: Mapped[str | None] = mapped_column(Text)
    response_time_ms: Mapped[float | None] = mapped_column(Float)
    run_id: Mapped[str | None] = mapped_column(String(32))
    is_summary: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
    )
    checked_at: Mapped[datetime] = mapped_column(UTCDateTime, server_default=func.now())


class HealthCurrentStatus(Base, IdentityMixin, TimestampMixin):
    """Bounded current health state for fast latest-status reads."""

    __tablename__ = "health_current_status"
    __table_args__ = (
        UniqueConstraint(
            "component",
            "subject_key_norm",
            "current_key",
            name="uq_health_current_status_identity",
        ),
        Index(
            "ix_health_current_component_summary",
            "component",
            "is_summary",
            "subject_key_norm",
        ),
        Index("ix_health_current_component_checked", "component", "checked_at"),
    )

    component: Mapped[str] = mapped_column(String(100), nullable=False)
    current_key: Mapped[str] = mapped_column(String(100), nullable=False)
    check_name: Mapped[str] = mapped_column(String(100), nullable=False)
    subject_key: Mapped[str | None] = mapped_column(String(100))
    subject_key_norm: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="",
        server_default="",
    )
    subject_label: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[HealthStatus] = mapped_column(SQLAlchemyEnum(HealthStatus), nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    details_json: Mapped[str | None] = mapped_column(Text)
    response_time_ms: Mapped[float | None] = mapped_column(Float)
    run_id: Mapped[str | None] = mapped_column(String(32))
    is_summary: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
    )
    checked_at: Mapped[datetime] = mapped_column(UTCDateTime, server_default=func.now())


class HealthIncident(Base, IdentityMixin, TimestampMixin):
    """Compact long-term record for non-healthy health status spans."""

    __tablename__ = "health_incidents"
    __table_args__ = (
        Index("ix_health_incident_component_active", "component", "resolved_at"),
        Index(
            "ix_health_incident_component_subject",
            "component",
            "subject_key_norm",
            "current_key",
        ),
        Index("ix_health_incident_last_seen", "last_seen_at"),
    )

    component: Mapped[str] = mapped_column(String(100), nullable=False)
    current_key: Mapped[str] = mapped_column(String(100), nullable=False)
    check_name: Mapped[str] = mapped_column(String(100), nullable=False)
    subject_key: Mapped[str | None] = mapped_column(String(100))
    subject_key_norm: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="",
        server_default="",
    )
    subject_label: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[HealthStatus] = mapped_column(SQLAlchemyEnum(HealthStatus), nullable=False)
    is_summary: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
    )
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    occurrence_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    last_message: Mapped[str | None] = mapped_column(Text)
    last_details_json: Mapped[str | None] = mapped_column(Text)
    last_response_time_ms: Mapped[float | None] = mapped_column(Float)
    last_run_id: Mapped[str | None] = mapped_column(String(32))
