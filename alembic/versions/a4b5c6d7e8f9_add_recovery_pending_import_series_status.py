"""Add recovery pending import-series status.

Revision ID: a4b5c6d7e8f9
Revises: b5c6d7e8f901
Create Date: 2026-05-21 14:10:00.000000
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "a4b5c6d7e8f9"
down_revision = "b5c6d7e8f901"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE importseriesstatus ADD VALUE IF NOT EXISTS 'RECOVERY_PENDING'")


def downgrade() -> None:
    # PostgreSQL enum value removal is intentionally omitted.
    pass
