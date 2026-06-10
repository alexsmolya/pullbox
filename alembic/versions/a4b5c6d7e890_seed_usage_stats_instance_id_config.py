"""Seed usage stats instance ID config.

Revision ID: a4b5c6d7e890
Revises: z2a3b4c5d678
Create Date: 2026-05-16
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "a4b5c6d7e890"
down_revision: str | Sequence[str] | None = "z2a3b4c5d678"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Seed the telemetry instance ID config key without generating an ID."""
    conn = op.get_bind()
    system_config = sa.table(
        "system_config",
        sa.column("key", sa.String),
        sa.column("value", sa.Text),
        sa.column("value_type", sa.String),
    )
    exists = conn.execute(
        sa.select(system_config.c.key).where(system_config.c.key == "usage_stats_instance_id")
    ).first()
    if not exists:
        conn.execute(
            system_config.insert().values(
                key="usage_stats_instance_id",
                value="",
                value_type="string",
            )
        )


def downgrade() -> None:
    """Remove the seeded telemetry instance ID config key."""
    system_config = sa.table("system_config", sa.column("key", sa.String))
    op.execute(system_config.delete().where(system_config.c.key == "usage_stats_instance_id"))
