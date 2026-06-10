"""add user session_version column

Revision ID: db06777618db
Revises: i4d5e6f7g890
Create Date: 2026-03-02 14:15:44.359207

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "db06777618db"
down_revision: str | Sequence[str] | None = "i4d5e6f7g890"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add session_version column to users table."""
    op.add_column(
        "users", sa.Column("session_version", sa.Integer(), server_default="0", nullable=False)
    )


def downgrade() -> None:
    """Remove session_version column from users table."""
    op.drop_column("users", "session_version")
