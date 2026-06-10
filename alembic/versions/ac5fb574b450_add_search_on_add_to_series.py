"""add search_on_add to series

Revision ID: ac5fb574b450
Revises: a4da6184985e
Create Date: 2026-03-03 13:44:44.677246

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ac5fb574b450"
down_revision: str | Sequence[str] | None = "a4da6184985e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add search_on_add boolean column to series table."""
    op.add_column(
        "series", sa.Column("search_on_add", sa.Boolean(), server_default="0", nullable=False)
    )


def downgrade() -> None:
    """Remove search_on_add column from series table."""
    op.drop_column("series", "search_on_add")
