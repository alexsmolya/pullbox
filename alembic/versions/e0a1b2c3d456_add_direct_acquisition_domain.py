"""Add dormant direct-download acquisition persistence.

Revision ID: e0a1b2c3d456
Revises: d9f0a1b2c345
Create Date: 2026-07-27
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "e0a1b2c3d456"
down_revision: str | Sequence[str] | None = "d9f0a1b2c345"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum(name: str, *values: str) -> sa.Enum:
    return sa.Enum(
        *values,
        name=name,
        native_enum=False,
        create_constraint=True,
    )


provider_state = _enum(
    "directproviderstate",
    "disabled",
    "healthy",
    "degraded",
    "rate_limited",
    "authentication_required",
    "incompatible",
    "unavailable",
)
provider_trust = _enum(
    "directprovidertrustlevel",
    "verified_pullbox",
    "custom",
)
host_kind = _enum(
    "directartifacthostkind",
    "generic_https",
    "pixeldrain",
    "mega",
    "rootz",
    "mediafire",
    "terabox",
    "datanodes",
)
host_account_state = _enum(
    "directhostaccountstate",
    "not_configured",
    "unknown",
    "healthy",
    "authentication_required",
    "quota_limited",
    "unavailable",
)
acquisition_state = _enum(
    "directacquisitionstate",
    "discovered",
    "resolving",
    "planned",
    "queued",
    "downloading",
    "validating",
    "post_processing",
    "completed",
    "retry_pending",
    "paused",
    "cancelled",
    "failed",
    "intervention",
)
artifact_state = _enum(
    "directartifactstate",
    "planned",
    "resolving",
    "transferring",
    "validating",
    "completed",
    "retry_pending",
    "paused",
    "cancelled",
    "failed",
    "intervention",
)
route_kind = _enum(
    "directartifactroutekind",
    "direct",
    "torrent_file",
    "magnet",
)
failure_class = _enum(
    "directartifactfailureclass",
    "provider_unavailable",
    "transient_source",
    "transient_host",
    "permanent_mirror",
    "unsupported_artifact_host",
    "artifact_host_auth_required",
    "artifact_host_challenge",
    "host_quota",
    "candidate_invalid",
    "resolver",
    "safety",
    "post_process",
    "user_action",
)


def upgrade() -> None:
    """Create dormant direct-download configuration and attempt tables."""
    op.create_table(
        "direct_provider_configs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("provider_id", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("endpoint", sa.String(length=1000), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("priority", sa.Integer(), server_default="50", nullable=False),
        sa.Column("state", provider_state, server_default="disabled", nullable=False),
        sa.Column("negotiated_protocol", sa.String(length=100), nullable=True),
        sa.Column("trust_level", provider_trust, server_default="custom", nullable=False),
        sa.Column("encrypted_bearer_token", sa.Text(), nullable=True),
        sa.Column(
            "encrypted_configuration",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "configuration_metadata",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "manifest_snapshot",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("resolver_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("last_health_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("priority >= 0", name="ck_direct_provider_priority_nonnegative"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("endpoint", name="uq_direct_provider_endpoint"),
        sa.UniqueConstraint("provider_id", name="uq_direct_provider_id"),
    )
    op.create_index(
        "ix_direct_provider_configs_state",
        "direct_provider_configs",
        ["state"],
    )
    op.create_index(
        "ix_direct_provider_configs_enabled_priority",
        "direct_provider_configs",
        ["enabled", "priority"],
    )

    op.create_table(
        "direct_host_configs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("host_kind", host_kind, nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("preference", sa.Integer(), server_default="50", nullable=False),
        sa.Column(
            "account_state",
            host_account_state,
            server_default="not_configured",
            nullable=False,
        ),
        sa.Column(
            "encrypted_credentials",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "account_metadata",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("quota_remaining", sa.BigInteger(), nullable=True),
        sa.Column("quota_reset_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("preference >= 0", name="ck_direct_host_preference_nonnegative"),
        sa.CheckConstraint(
            "quota_remaining IS NULL OR quota_remaining >= 0",
            name="ck_direct_host_quota_nonnegative",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("host_kind", name="uq_direct_host_kind"),
    )
    op.create_index(
        "ix_direct_host_configs_account_state",
        "direct_host_configs",
        ["account_state"],
    )
    op.create_index(
        "ix_direct_host_configs_enabled_preference",
        "direct_host_configs",
        ["enabled", "preference"],
    )

    op.create_table(
        "direct_acquisition_attempts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("request_key", sa.String(length=255), nullable=False),
        sa.Column("issue_id", sa.Integer(), nullable=False),
        sa.Column("search_log_id", sa.Integer(), nullable=True),
        sa.Column("provider_config_id", sa.Integer(), nullable=True),
        sa.Column("provider_identity", sa.String(length=255), nullable=False),
        sa.Column("provider_candidate_id", sa.String(length=500), nullable=False),
        sa.Column("state", acquisition_state, server_default="discovered", nullable=False),
        sa.Column(
            "requested_coverage",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "candidate_snapshot",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "plan_snapshot",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("plan_revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "progress_snapshot",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("progress_revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_retries", sa.Integer(), server_default="3", nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_class", failure_class, nullable=True),
        sa.Column("failure_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "replace_existing_file",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("library_file_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("plan_revision >= 0", name="ck_direct_plan_revision_nonnegative"),
        sa.CheckConstraint(
            "progress_revision >= 0",
            name="ck_direct_progress_revision_nonnegative",
        ),
        sa.CheckConstraint("retry_count >= 0", name="ck_direct_retry_count_nonnegative"),
        sa.CheckConstraint("max_retries >= 0", name="ck_direct_max_retries_nonnegative"),
        sa.ForeignKeyConstraint(["issue_id"], ["issues.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["library_file_id"],
            ["library_files.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["provider_config_id"],
            ["direct_provider_configs.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["search_log_id"],
            ["search_logs.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_key", name="uq_direct_acquisition_request_key"),
    )
    op.create_index(
        "ix_direct_acquisition_attempts_state_retry",
        "direct_acquisition_attempts",
        ["state", "next_retry_at"],
    )
    op.create_index(
        "ix_direct_acquisition_attempts_issue_created",
        "direct_acquisition_attempts",
        ["issue_id", "created_at"],
    )
    op.create_index(
        "ix_direct_acquisition_attempts_provider_state",
        "direct_acquisition_attempts",
        ["provider_config_id", "state"],
    )

    op.create_table(
        "direct_artifact_attempts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("acquisition_attempt_id", sa.Integer(), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("artifact_identity", sa.String(length=500), nullable=False),
        sa.Column("route_kind", route_kind, nullable=False),
        sa.Column("host_kind", host_kind, nullable=False),
        sa.Column("state", artifact_state, server_default="planned", nullable=False),
        sa.Column("is_selected", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("expected_size", sa.BigInteger(), nullable=True),
        sa.Column("bytes_transferred", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("etag", sa.String(length=500), nullable=True),
        sa.Column("last_modified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("quarantine_path", sa.String(length=1000), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_retries", sa.Integer(), server_default="3", nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_class", failure_class, nullable=True),
        sa.Column("failure_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("sequence_no >= 0", name="ck_direct_artifact_sequence_nonnegative"),
        sa.CheckConstraint(
            "expected_size IS NULL OR expected_size >= 0",
            name="ck_direct_artifact_expected_size_nonnegative",
        ),
        sa.CheckConstraint(
            "bytes_transferred >= 0",
            name="ck_direct_artifact_bytes_nonnegative",
        ),
        sa.CheckConstraint(
            "retry_count >= 0",
            name="ck_direct_artifact_retry_count_nonnegative",
        ),
        sa.CheckConstraint(
            "max_retries >= 0",
            name="ck_direct_artifact_max_retries_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["acquisition_attempt_id"],
            ["direct_acquisition_attempts.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "acquisition_attempt_id",
            "artifact_identity",
            name="uq_direct_artifact_identity",
        ),
        sa.UniqueConstraint(
            "acquisition_attempt_id",
            "sequence_no",
            name="uq_direct_artifact_sequence",
        ),
    )
    op.create_index(
        "ix_direct_artifact_attempts_acquisition_sequence",
        "direct_artifact_attempts",
        ["acquisition_attempt_id", "sequence_no"],
    )
    op.create_index(
        "ix_direct_artifact_attempts_state_retry",
        "direct_artifact_attempts",
        ["state", "next_retry_at"],
    )
    op.create_index(
        "ix_direct_artifact_attempts_host_state",
        "direct_artifact_attempts",
        ["host_kind", "state"],
    )


def downgrade() -> None:
    """Remove only the dormant direct-download persistence structures."""
    op.drop_index(
        "ix_direct_artifact_attempts_host_state",
        table_name="direct_artifact_attempts",
    )
    op.drop_index(
        "ix_direct_artifact_attempts_state_retry",
        table_name="direct_artifact_attempts",
    )
    op.drop_index(
        "ix_direct_artifact_attempts_acquisition_sequence",
        table_name="direct_artifact_attempts",
    )
    op.drop_table("direct_artifact_attempts")

    op.drop_index(
        "ix_direct_acquisition_attempts_provider_state",
        table_name="direct_acquisition_attempts",
    )
    op.drop_index(
        "ix_direct_acquisition_attempts_issue_created",
        table_name="direct_acquisition_attempts",
    )
    op.drop_index(
        "ix_direct_acquisition_attempts_state_retry",
        table_name="direct_acquisition_attempts",
    )
    op.drop_table("direct_acquisition_attempts")

    op.drop_index(
        "ix_direct_host_configs_enabled_preference",
        table_name="direct_host_configs",
    )
    op.drop_index(
        "ix_direct_host_configs_account_state",
        table_name="direct_host_configs",
    )
    op.drop_table("direct_host_configs")

    op.drop_index(
        "ix_direct_provider_configs_enabled_priority",
        table_name="direct_provider_configs",
    )
    op.drop_index(
        "ix_direct_provider_configs_state",
        table_name="direct_provider_configs",
    )
    op.drop_table("direct_provider_configs")
