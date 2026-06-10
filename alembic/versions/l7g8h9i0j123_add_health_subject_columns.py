"""Add health subject identity columns.

Revision ID: l7g8h9i0j123
Revises: k6f7g8h9i012
Create Date: 2026-04-21
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "l7g8h9i0j123"
down_revision = "k6f7g8h9i012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add subject metadata for multi-entity health components."""
    op.add_column(
        "health_check_results",
        sa.Column("subject_key", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "health_check_results",
        sa.Column("subject_label", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "ix_health_check_component_subject_summary_time",
        "health_check_results",
        ["component", "subject_key", "is_summary", "checked_at"],
        unique=False,
    )
    op.create_index(
        "ix_health_check_component_subject_run",
        "health_check_results",
        ["component", "subject_key", "run_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove subject metadata for multi-entity health components."""
    op.drop_index("ix_health_check_component_subject_run", table_name="health_check_results")
    op.drop_index(
        "ix_health_check_component_subject_summary_time",
        table_name="health_check_results",
    )
    op.drop_column("health_check_results", "subject_label")
    op.drop_column("health_check_results", "subject_key")
