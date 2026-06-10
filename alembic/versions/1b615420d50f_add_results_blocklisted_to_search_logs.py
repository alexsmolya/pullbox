"""add results_blocklisted to search_logs

Revision ID: 1b615420d50f
Revises: ab13e773209d
Create Date: 2026-03-20 18:14:00.879322

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1b615420d50f"
down_revision: str | Sequence[str] | None = "ab13e773209d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add results_blocklisted counter to search_logs."""
    op.add_column(
        "search_logs",
        sa.Column("results_blocklisted", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    """Remove results_blocklisted from search_logs."""
    op.drop_column("search_logs", "results_blocklisted")
