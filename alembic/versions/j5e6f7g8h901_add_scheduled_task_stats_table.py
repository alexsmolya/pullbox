"""Add scheduled_task_stats table.

Revision ID: j5e6f7g8h901
Revises: 6b7c8d9e0f12
Create Date: 2026-04-20
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import sqlalchemy as sa

from alembic import op

revision = "j5e6f7g8h901"
down_revision = "6b7c8d9e0f12"
branch_labels = None
depends_on = None


def _parse_datetime(value: Any) -> datetime | None:
    """Parse stored ISO timestamps when migrating legacy stats."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def upgrade() -> None:
    """Create per-task scheduler stats storage and migrate legacy JSON rows."""
    op.create_table(
        "scheduled_task_stats",
        sa.Column("task_id", sa.String(length=255), nullable=False),
        sa.Column("last_execution", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_duration_seconds", sa.Float(), nullable=True),
        sa.Column("last_status", sa.String(length=32), nullable=True),
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
        sa.PrimaryKeyConstraint("task_id"),
    )

    bind = op.get_bind()
    legacy = bind.execute(
        sa.text("SELECT value FROM system_config WHERE key = 'scheduler_task_stats'")
    ).scalar_one_or_none()
    if not legacy:
        return

    try:
        payload = json.loads(legacy)
    except (TypeError, ValueError):
        return
    if not isinstance(payload, dict):
        return

    rows: list[dict[str, Any]] = []
    for task_id, raw in payload.items():
        if not isinstance(task_id, str) or not isinstance(raw, dict):
            continue
        rows.append(
            {
                "task_id": task_id,
                "last_execution": _parse_datetime(raw.get("last_execution")),
                "last_duration_seconds": raw.get("last_duration_seconds"),
                "last_status": raw.get("last_status"),
            }
        )
    if rows:
        op.bulk_insert(
            sa.table(
                "scheduled_task_stats",
                sa.column("task_id", sa.String),
                sa.column("last_execution", sa.DateTime(timezone=True)),
                sa.column("last_duration_seconds", sa.Float),
                sa.column("last_status", sa.String),
            ),
            rows,
        )


def downgrade() -> None:
    """Drop per-task scheduler stats storage."""
    op.drop_table("scheduled_task_stats")
