"""Add optional direct-download browser resolver configuration.

Revision ID: f1b2c3d4e5f6
Revises: e0a1b2c3d456
Create Date: 2026-07-27
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "f1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "e0a1b2c3d456"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


resolver_state = sa.Enum(
    "disabled",
    "unknown",
    "healthy",
    "degraded",
    "authentication_required",
    "incompatible",
    "unavailable",
    name="directresolverstate",
    native_enum=False,
    create_constraint=True,
)


def upgrade() -> None:
    op.create_table(
        "direct_resolver_configs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=100), server_default="default", nullable=False),
        sa.Column("endpoint", sa.String(length=1000), server_default="", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("state", resolver_state, server_default="disabled", nullable=False),
        sa.Column(
            "allow_private_http",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("timeout_seconds", sa.Integer(), server_default="60", nullable=False),
        sa.Column("max_concurrency", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "encrypted_auth_headers",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "auth_metadata",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
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
        sa.CheckConstraint(
            "timeout_seconds > 0 AND timeout_seconds <= 300",
            name="ck_direct_resolver_timeout",
        ),
        sa.CheckConstraint(
            "max_concurrency >= 1 AND max_concurrency <= 4",
            name="ck_direct_resolver_concurrency",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_direct_resolver_name"),
    )


def downgrade() -> None:
    op.drop_table("direct_resolver_configs")
