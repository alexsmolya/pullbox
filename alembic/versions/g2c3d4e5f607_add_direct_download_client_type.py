"""Add the direct acquisition download-client discriminator.

Revision ID: g2c3d4e5f607
Revises: f1b2c3d4e5f6
Create Date: 2026-07-28
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "g2c3d4e5f607"
down_revision: str | Sequence[str] | None = "f1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Allow direct history rows on PostgreSQL; SQLite stores this enum as text."""
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TYPE downloadclienttype ADD VALUE IF NOT EXISTS 'DIRECT'")


def downgrade() -> None:
    """Keep the PostgreSQL enum value because removing enum values is unsafe."""
