"""add series alternate_names

Revision ID: 119149955c0a
Revises: h3c4d5e6f789
Create Date: 2026-03-01 14:14:11.112656

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "119149955c0a"
down_revision: str | Sequence[str] | None = "h3c4d5e6f789"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add alternate_names JSON column to series table."""
    op.add_column(
        "series", sa.Column("alternate_names", sa.JSON(), server_default="[]", nullable=False)
    )


def downgrade() -> None:
    """Remove alternate_names column from series table."""
    op.drop_column("series", "alternate_names")
