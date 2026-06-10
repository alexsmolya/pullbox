"""Add exclusive-block tracking fields to scheduled_task_stats.

Revision ID: u6p7q8r9s012
Revises: t5o6p7q8r901
Create Date: 2026-05-02
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "u6p7q8r9s012"
down_revision = "t5o6p7q8r901"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add exclusive-task block stats to persisted scheduler rows."""
    op.add_column(
        "scheduled_task_stats",
        sa.Column("last_exclusive_block_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "scheduled_task_stats",
        sa.Column("exclusive_block_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    """Remove exclusive-task block stats from persisted scheduler rows."""
    op.drop_column("scheduled_task_stats", "exclusive_block_count")
    op.drop_column("scheduled_task_stats", "last_exclusive_block_at")
