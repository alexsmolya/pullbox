"""Remove scheduled task run history table.

Revision ID: s4n5o6p7q890
Revises: r3m4n5o6p789
Create Date: 2026-05-01
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "s4n5o6p7q890"
down_revision = "r3m4n5o6p789"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Drop persisted scheduler run history storage."""
    op.drop_index("ix_scheduled_task_runs_task_started", table_name="scheduled_task_runs")
    op.drop_index("ix_scheduled_task_runs_task_completed", table_name="scheduled_task_runs")
    op.drop_index("ix_scheduled_task_runs_run_id", table_name="scheduled_task_runs")
    op.drop_table("scheduled_task_runs")


def downgrade() -> None:
    """Recreate persisted scheduler run history storage."""
    op.create_table(
        "scheduled_task_runs",
        sa.Column("task_id", sa.String(length=255), nullable=False),
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("trigger_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
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
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_scheduled_task_runs_run_id",
        "scheduled_task_runs",
        ["run_id"],
        unique=True,
    )
    op.create_index(
        "ix_scheduled_task_runs_task_completed",
        "scheduled_task_runs",
        ["task_id", "completed_at"],
        unique=False,
    )
    op.create_index(
        "ix_scheduled_task_runs_task_started",
        "scheduled_task_runs",
        ["task_id", "started_at"],
        unique=False,
    )
