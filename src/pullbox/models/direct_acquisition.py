"""Durable configuration and attempt records for direct acquisition."""

from __future__ import annotations

import enum
from datetime import datetime  # noqa: TC003 - SQLAlchemy needs this at runtime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pullbox.models.base import Base, IdentityMixin, TimestampMixin, UTCDateTime

if TYPE_CHECKING:
    from pullbox.models.issue import Issue
    from pullbox.models.library import LibraryFile
    from pullbox.models.search_log import SearchLog


def _enum_values(enum_class: type[enum.Enum]) -> list[str]:
    """Persist public enum values rather than Python member names."""
    return [str(member.value) for member in enum_class]


def _enum_type(enum_class: type[enum.Enum], name: str) -> SQLAlchemyEnum:
    """Build a portable constrained string enum for SQLite and PostgreSQL."""
    return SQLAlchemyEnum(
        enum_class,
        name=name,
        native_enum=False,
        create_constraint=True,
        values_callable=_enum_values,
    )


class DirectProviderState(enum.StrEnum):
    DISABLED = "disabled"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    RATE_LIMITED = "rate_limited"
    AUTHENTICATION_REQUIRED = "authentication_required"
    INCOMPATIBLE = "incompatible"
    UNAVAILABLE = "unavailable"


class DirectResolverState(enum.StrEnum):
    DISABLED = "disabled"
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    AUTHENTICATION_REQUIRED = "authentication_required"
    INCOMPATIBLE = "incompatible"
    UNAVAILABLE = "unavailable"


class DirectResolverKind(enum.StrEnum):
    FLARESOLVERR = "flaresolverr"
    BYPARR = "byparr"
    TRAWL = "trawl"


class DirectProviderTrustLevel(enum.StrEnum):
    VERIFIED_PULLBOX = "verified_pullbox"
    CUSTOM = "custom"


class DirectResolverConfig(Base, IdentityMixin, TimestampMixin):
    """One ranked optional browser challenge resolver profile."""

    __tablename__ = "direct_resolver_configs"
    __table_args__ = (
        UniqueConstraint("name", name="uq_direct_resolver_name"),
        UniqueConstraint("resolver_kind", name="uq_direct_resolver_kind"),
        CheckConstraint(
            "priority > 0 AND priority <= 1000",
            name="ck_direct_resolver_priority",
        ),
        CheckConstraint(
            "timeout_seconds > 0 AND timeout_seconds <= 300",
            name="ck_direct_resolver_timeout",
        ),
        CheckConstraint(
            "max_concurrency >= 1 AND max_concurrency <= 4",
            name="ck_direct_resolver_concurrency",
        ),
    )

    name: Mapped[str] = mapped_column(
        String(100),
        default="default",
        server_default="default",
        nullable=False,
    )
    resolver_kind: Mapped[DirectResolverKind] = mapped_column(
        _enum_type(DirectResolverKind, "directresolverkind"),
        default=DirectResolverKind.FLARESOLVERR,
        server_default=DirectResolverKind.FLARESOLVERR.value,
        nullable=False,
    )
    priority: Mapped[int] = mapped_column(
        Integer,
        default=10,
        server_default="10",
        nullable=False,
    )
    endpoint: Mapped[str] = mapped_column(String(1000), default="", server_default="")
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="0",
        nullable=False,
    )
    state: Mapped[DirectResolverState] = mapped_column(
        _enum_type(DirectResolverState, "directresolverstate"),
        default=DirectResolverState.DISABLED,
        server_default=DirectResolverState.DISABLED.value,
        nullable=False,
    )
    allow_private_http: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="0",
        nullable=False,
    )
    timeout_seconds: Mapped[int] = mapped_column(
        Integer,
        default=60,
        server_default="60",
        nullable=False,
    )
    max_concurrency: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default="1",
        nullable=False,
    )
    encrypted_auth_headers: Mapped[dict[str, object]] = mapped_column(
        JSON,
        default=dict,
        server_default="{}",
        nullable=False,
    )
    auth_metadata: Mapped[dict[str, object]] = mapped_column(
        JSON,
        default=dict,
        server_default="{}",
        nullable=False,
    )
    last_health_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_tested_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_error_code: Mapped[str | None] = mapped_column(String(100))


class DirectArtifactHostKind(enum.StrEnum):
    GENERIC_HTTPS = "generic_https"
    PIXELDRAIN = "pixeldrain"
    MEGA = "mega"
    ROOTZ = "rootz"
    MEDIAFIRE = "mediafire"
    TERABOX = "terabox"
    DATANODES = "datanodes"


class DirectHostAccountState(enum.StrEnum):
    NOT_CONFIGURED = "not_configured"
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    AUTHENTICATION_REQUIRED = "authentication_required"
    QUOTA_LIMITED = "quota_limited"
    UNAVAILABLE = "unavailable"


class DirectHostReachabilityState(enum.StrEnum):
    """What Pullbox most recently proved without downloading an artifact."""

    NOT_CHECKED = "not_checked"
    REACHABLE = "reachable"
    NOT_REACHABLE = "not_reachable"
    AUTHENTICATION_REQUIRED = "authentication_required"
    QUOTA_LIMITED = "quota_limited"
    UNAVAILABLE = "unavailable"


class DirectHostOperationalResult(enum.StrEnum):
    """Outcome of the most recent user-requested artifact-host operation."""

    SUCCESSFUL = "successful"
    FAILED = "failed"


class DirectAcquisitionState(enum.StrEnum):
    DISCOVERED = "discovered"
    RESOLVING = "resolving"
    PLANNED = "planned"
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    VALIDATING = "validating"
    POST_PROCESSING = "post_processing"
    COMPLETED = "completed"
    RETRY_PENDING = "retry_pending"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    FAILED = "failed"
    INTERVENTION = "intervention"


class DirectArtifactState(enum.StrEnum):
    PLANNED = "planned"
    RESOLVING = "resolving"
    TRANSFERRING = "transferring"
    VALIDATING = "validating"
    COMPLETED = "completed"
    RETRY_PENDING = "retry_pending"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    FAILED = "failed"
    INTERVENTION = "intervention"


class DirectArtifactRouteKind(enum.StrEnum):
    DIRECT = "direct"
    TORRENT_FILE = "torrent_file"
    MAGNET = "magnet"


class DirectArtifactFailureClass(enum.StrEnum):
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    TRANSIENT_SOURCE = "transient_source"
    TRANSIENT_HOST = "transient_host"
    PERMANENT_MIRROR = "permanent_mirror"
    UNSUPPORTED_ARTIFACT_HOST = "unsupported_artifact_host"
    ARTIFACT_HOST_AUTH_REQUIRED = "artifact_host_auth_required"
    ARTIFACT_HOST_CHALLENGE = "artifact_host_challenge"
    HOST_QUOTA = "host_quota"
    CANDIDATE_INVALID = "candidate_invalid"
    RESOLVER = "resolver"
    UNSAFE_ROUTE = "unsafe_route"
    SAFETY = "safety"
    POST_PROCESS = "post_process"
    USER_ACTION = "user_action"


class DirectProviderConfig(Base, IdentityMixin, TimestampMixin):
    """A manually registered stateless direct-discovery provider."""

    __tablename__ = "direct_provider_configs"
    __table_args__ = (
        UniqueConstraint("provider_id", name="uq_direct_provider_id"),
        UniqueConstraint("endpoint", name="uq_direct_provider_endpoint"),
        CheckConstraint("priority >= 0", name="ck_direct_provider_priority_nonnegative"),
        Index("ix_direct_provider_configs_state", "state"),
        Index("ix_direct_provider_configs_enabled_priority", "enabled", "priority"),
    )

    provider_id: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(1000), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="0",
        nullable=False,
    )
    priority: Mapped[int] = mapped_column(Integer, default=50, server_default="50", nullable=False)
    state: Mapped[DirectProviderState] = mapped_column(
        _enum_type(DirectProviderState, "directproviderstate"),
        default=DirectProviderState.DISABLED,
        server_default=DirectProviderState.DISABLED.value,
        nullable=False,
    )
    negotiated_protocol: Mapped[str | None] = mapped_column(String(100))
    trust_level: Mapped[DirectProviderTrustLevel] = mapped_column(
        _enum_type(DirectProviderTrustLevel, "directprovidertrustlevel"),
        default=DirectProviderTrustLevel.CUSTOM,
        server_default=DirectProviderTrustLevel.CUSTOM.value,
        nullable=False,
    )
    encrypted_bearer_token: Mapped[str | None] = mapped_column(Text)
    encrypted_configuration: Mapped[dict[str, object]] = mapped_column(
        JSON,
        default=dict,
        server_default="{}",
        nullable=False,
    )
    configuration_metadata: Mapped[dict[str, object]] = mapped_column(
        JSON,
        default=dict,
        server_default="{}",
        nullable=False,
    )
    manifest_snapshot: Mapped[dict[str, object]] = mapped_column(
        JSON,
        default=dict,
        server_default="{}",
        nullable=False,
    )
    resolver_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="0",
        nullable=False,
    )
    last_health_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_tested_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_error_code: Mapped[str | None] = mapped_column(String(100))

    acquisition_attempts: Mapped[list[DirectAcquisitionAttempt]] = relationship(
        back_populates="provider_config",
        passive_deletes=True,
    )


class DirectHostConfig(Base, IdentityMixin, TimestampMixin):
    """Pullbox-owned settings and encrypted account state for one artifact host."""

    __tablename__ = "direct_host_configs"
    __table_args__ = (
        UniqueConstraint("host_kind", name="uq_direct_host_kind"),
        CheckConstraint("preference >= 0", name="ck_direct_host_preference_nonnegative"),
        CheckConstraint(
            "quota_remaining IS NULL OR quota_remaining >= 0",
            name="ck_direct_host_quota_nonnegative",
        ),
        Index("ix_direct_host_configs_account_state", "account_state"),
        Index("ix_direct_host_configs_enabled_preference", "enabled", "preference"),
    )

    host_kind: Mapped[DirectArtifactHostKind] = mapped_column(
        _enum_type(DirectArtifactHostKind, "directartifacthostkind"),
        nullable=False,
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="0",
        nullable=False,
    )
    preference: Mapped[int] = mapped_column(
        Integer,
        default=50,
        server_default="50",
        nullable=False,
    )
    account_state: Mapped[DirectHostAccountState] = mapped_column(
        _enum_type(DirectHostAccountState, "directhostaccountstate"),
        default=DirectHostAccountState.NOT_CONFIGURED,
        server_default=DirectHostAccountState.NOT_CONFIGURED.value,
        nullable=False,
    )
    encrypted_credentials: Mapped[dict[str, object]] = mapped_column(
        JSON,
        default=dict,
        server_default="{}",
        nullable=False,
    )
    account_metadata: Mapped[dict[str, object]] = mapped_column(
        JSON,
        default=dict,
        server_default="{}",
        nullable=False,
    )
    quota_remaining: Mapped[int | None] = mapped_column(BigInteger)
    quota_reset_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    reachability_state: Mapped[DirectHostReachabilityState] = mapped_column(
        _enum_type(DirectHostReachabilityState, "directhostreachabilitystate"),
        default=DirectHostReachabilityState.NOT_CHECKED,
        server_default=DirectHostReachabilityState.NOT_CHECKED.value,
        nullable=False,
    )
    last_tested_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_reachable_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_operational_result: Mapped[DirectHostOperationalResult | None] = mapped_column(
        _enum_type(DirectHostOperationalResult, "directhostoperationalresult")
    )
    last_operational_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_error_code: Mapped[str | None] = mapped_column(String(100))


class DirectAcquisitionAttempt(Base, IdentityMixin, TimestampMixin):
    """A restart-safe logical direct acquisition selected for one issue."""

    __tablename__ = "direct_acquisition_attempts"
    __table_args__ = (
        UniqueConstraint("request_key", name="uq_direct_acquisition_request_key"),
        CheckConstraint("plan_revision >= 0", name="ck_direct_plan_revision_nonnegative"),
        CheckConstraint(
            "progress_revision >= 0",
            name="ck_direct_progress_revision_nonnegative",
        ),
        CheckConstraint("retry_count >= 0", name="ck_direct_retry_count_nonnegative"),
        CheckConstraint("max_retries >= 0", name="ck_direct_max_retries_nonnegative"),
        Index("ix_direct_acquisition_attempts_state_retry", "state", "next_retry_at"),
        Index("ix_direct_acquisition_attempts_issue_created", "issue_id", "created_at"),
        Index(
            "ix_direct_acquisition_attempts_provider_state",
            "provider_config_id",
            "state",
        ),
    )

    request_key: Mapped[str] = mapped_column(String(255), nullable=False)
    issue_id: Mapped[int] = mapped_column(
        ForeignKey("issues.id", ondelete="CASCADE"),
        nullable=False,
    )
    search_log_id: Mapped[int | None] = mapped_column(
        ForeignKey("search_logs.id", ondelete="SET NULL")
    )
    provider_config_id: Mapped[int | None] = mapped_column(
        ForeignKey("direct_provider_configs.id", ondelete="SET NULL")
    )
    provider_identity: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_candidate_id: Mapped[str] = mapped_column(String(500), nullable=False)
    state: Mapped[DirectAcquisitionState] = mapped_column(
        _enum_type(DirectAcquisitionState, "directacquisitionstate"),
        default=DirectAcquisitionState.DISCOVERED,
        server_default=DirectAcquisitionState.DISCOVERED.value,
        nullable=False,
    )
    requested_coverage: Mapped[dict[str, object]] = mapped_column(
        JSON,
        default=dict,
        server_default="{}",
        nullable=False,
    )
    candidate_snapshot: Mapped[dict[str, object]] = mapped_column(
        JSON,
        default=dict,
        server_default="{}",
        nullable=False,
    )
    plan_snapshot: Mapped[dict[str, object]] = mapped_column(
        JSON,
        default=dict,
        server_default="{}",
        nullable=False,
    )
    plan_revision: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    progress_snapshot: Mapped[dict[str, object]] = mapped_column(
        JSON,
        default=dict,
        server_default="{}",
        nullable=False,
    )
    progress_revision: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    retry_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    max_retries: Mapped[int] = mapped_column(
        Integer,
        default=3,
        server_default="3",
        nullable=False,
    )
    next_retry_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    failure_class: Mapped[DirectArtifactFailureClass | None] = mapped_column(
        _enum_type(DirectArtifactFailureClass, "directartifactfailureclass")
    )
    failure_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    replace_existing_file: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="0",
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    cancelled_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    library_file_id: Mapped[int | None] = mapped_column(
        ForeignKey("library_files.id", ondelete="SET NULL")
    )

    issue: Mapped[Issue] = relationship()
    search_log: Mapped[SearchLog | None] = relationship()
    provider_config: Mapped[DirectProviderConfig | None] = relationship(
        back_populates="acquisition_attempts"
    )
    library_file: Mapped[LibraryFile | None] = relationship()
    artifact_attempts: Mapped[list[DirectArtifactAttempt]] = relationship(
        back_populates="acquisition_attempt",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="DirectArtifactAttempt.sequence_no",
        lazy="selectin",
    )


class DirectArtifactAttempt(Base, IdentityMixin, TimestampMixin):
    """One ordered mirror or artifact transfer attempt within an acquisition."""

    __tablename__ = "direct_artifact_attempts"
    __table_args__ = (
        UniqueConstraint(
            "acquisition_attempt_id",
            "artifact_identity",
            name="uq_direct_artifact_identity",
        ),
        UniqueConstraint(
            "acquisition_attempt_id",
            "sequence_no",
            name="uq_direct_artifact_sequence",
        ),
        CheckConstraint(
            "sequence_no >= 0",
            name="ck_direct_artifact_sequence_nonnegative",
        ),
        CheckConstraint(
            "expected_size IS NULL OR expected_size >= 0",
            name="ck_direct_artifact_expected_size_nonnegative",
        ),
        CheckConstraint(
            "bytes_transferred >= 0",
            name="ck_direct_artifact_bytes_nonnegative",
        ),
        CheckConstraint(
            "retry_count >= 0",
            name="ck_direct_artifact_retry_count_nonnegative",
        ),
        CheckConstraint(
            "max_retries >= 0",
            name="ck_direct_artifact_max_retries_nonnegative",
        ),
        Index(
            "ix_direct_artifact_attempts_acquisition_sequence",
            "acquisition_attempt_id",
            "sequence_no",
        ),
        Index("ix_direct_artifact_attempts_state_retry", "state", "next_retry_at"),
        Index("ix_direct_artifact_attempts_host_state", "host_kind", "state"),
    )

    acquisition_attempt_id: Mapped[int] = mapped_column(
        ForeignKey("direct_acquisition_attempts.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    artifact_identity: Mapped[str] = mapped_column(String(500), nullable=False)
    route_kind: Mapped[DirectArtifactRouteKind] = mapped_column(
        _enum_type(DirectArtifactRouteKind, "directartifactroutekind"),
        nullable=False,
    )
    host_kind: Mapped[DirectArtifactHostKind] = mapped_column(
        _enum_type(DirectArtifactHostKind, "directartifacthostkind"),
        nullable=False,
    )
    state: Mapped[DirectArtifactState] = mapped_column(
        _enum_type(DirectArtifactState, "directartifactstate"),
        default=DirectArtifactState.PLANNED,
        server_default=DirectArtifactState.PLANNED.value,
        nullable=False,
    )
    is_selected: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="0",
        nullable=False,
    )
    expected_size: Mapped[int | None] = mapped_column(BigInteger)
    bytes_transferred: Mapped[int] = mapped_column(
        BigInteger,
        default=0,
        server_default="0",
        nullable=False,
    )
    etag: Mapped[str | None] = mapped_column(String(500))
    last_modified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    quarantine_path: Mapped[str | None] = mapped_column(String(1000))
    retry_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    max_retries: Mapped[int] = mapped_column(
        Integer,
        default=3,
        server_default="3",
        nullable=False,
    )
    next_retry_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    failure_class: Mapped[DirectArtifactFailureClass | None] = mapped_column(
        _enum_type(DirectArtifactFailureClass, "directartifactfailureclass")
    )
    failure_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    acquisition_attempt: Mapped[DirectAcquisitionAttempt] = relationship(
        back_populates="artifact_attempts"
    )
