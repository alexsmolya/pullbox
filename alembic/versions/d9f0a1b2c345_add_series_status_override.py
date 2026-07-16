"""Add a manual series lifecycle status override.

Revision ID: d9f0a1b2c345
Revises: c8e1f4a7b902
Create Date: 2026-07-16
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "d9f0a1b2c345"
down_revision: str | Sequence[str] | None = "c8e1f4a7b902"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

status_override_enum = sa.Enum(
    "CONTINUING",
    "ENDED",
    name="seriesstatusoverride",
)


def upgrade() -> None:
    """Add the nullable user-owned lifecycle status."""
    status_override_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "series",
        sa.Column("status_override", status_override_enum, nullable=True),
    )


def downgrade() -> None:
    """Remove the lifecycle override and its PostgreSQL enum."""
    op.drop_column("series", "status_override")
    status_override_enum.drop(op.get_bind(), checkfirst=True)
