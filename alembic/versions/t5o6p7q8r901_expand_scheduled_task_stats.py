"""Expand scheduled_task_stats fields and enforce process-completed floor.

Revision ID: t5o6p7q8r901
Revises: s4n5o6p7q890
Create Date: 2026-05-01
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "t5o6p7q8r901"
down_revision = "s4n5o6p7q890"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add overlap/missed fields and clamp old process-completed intervals."""
    op.add_column(
        "scheduled_task_stats",
        sa.Column("last_missed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "scheduled_task_stats",
        sa.Column("missed_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "scheduled_task_stats",
        sa.Column("last_overlap_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "scheduled_task_stats",
        sa.Column("overlap_count", sa.Integer(), nullable=False, server_default="0"),
    )

    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE system_config
            SET value = '300'
            WHERE key = 'process_completed_interval_seconds'
              AND CAST(value AS INTEGER) < 300
            """
        )
    )


def downgrade() -> None:
    """Remove overlap/missed fields and restore legacy task-stat shape."""
    op.drop_column("scheduled_task_stats", "overlap_count")
    op.drop_column("scheduled_task_stats", "last_overlap_at")
    op.drop_column("scheduled_task_stats", "missed_count")
    op.drop_column("scheduled_task_stats", "last_missed_at")
