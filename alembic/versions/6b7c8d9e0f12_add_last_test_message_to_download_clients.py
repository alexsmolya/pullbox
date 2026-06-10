"""Add last_test_message to download client configs.

Revision ID: 6b7c8d9e0f12
Revises: 5f4a3c2b1d90
Create Date: 2026-04-20
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "6b7c8d9e0f12"
down_revision: str | Sequence[str] | None = "5f4a3c2b1d90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add last-known test message storage for download clients."""
    op.add_column(
        "download_client_configs",
        sa.Column("last_test_message", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Remove last-known test message storage from download clients."""
    op.drop_column("download_client_configs", "last_test_message")
