"""add health incidents

Revision ID: e7f8g9h0i123
Revises: d6e7f8g9h012
Create Date: 2026-05-29
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "e7f8g9h0i123"
down_revision: str | Sequence[str] | None = "d6e7f8g9h012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "health_incidents",
        sa.Column("component", sa.String(length=100), nullable=False),
        sa.Column("current_key", sa.String(length=100), nullable=False),
        sa.Column("check_name", sa.String(length=100), nullable=False),
        sa.Column("subject_key", sa.String(length=100), nullable=True),
        sa.Column("subject_key_norm", sa.String(length=100), server_default="", nullable=False),
        sa.Column("subject_label", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=9), nullable=False),
        sa.Column("is_summary", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("occurrence_count", sa.Integer(), server_default="1", nullable=False),
        sa.Column("last_message", sa.Text(), nullable=True),
        sa.Column("last_details_json", sa.Text(), nullable=True),
        sa.Column("last_response_time_ms", sa.Float(), nullable=True),
        sa.Column("last_run_id", sa.String(length=32), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_health_incident_component_active",
        "health_incidents",
        ["component", "resolved_at"],
    )
    op.create_index(
        "ix_health_incident_component_subject",
        "health_incidents",
        ["component", "subject_key_norm", "current_key"],
    )
    op.create_index(
        "ix_health_incident_last_seen",
        "health_incidents",
        ["last_seen_at"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_health_incident_last_seen", table_name="health_incidents")
    op.drop_index("ix_health_incident_component_subject", table_name="health_incidents")
    op.drop_index("ix_health_incident_component_active", table_name="health_incidents")
    op.drop_table("health_incidents")
