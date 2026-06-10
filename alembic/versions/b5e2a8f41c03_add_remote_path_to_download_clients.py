"""add remote_path to download_client_configs

Revision ID: b5e2a8f41c03
Revises: a3f7b1c82d01
Create Date: 2026-02-24 21:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b5e2a8f41c03"
down_revision: str | Sequence[str] | None = "a3f7b1c82d01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add remote_path column to download_client_configs."""
    op.add_column(
        "download_client_configs",
        sa.Column("remote_path", sa.String(1000), nullable=True),
    )


def downgrade() -> None:
    """Remove remote_path column from download_client_configs."""
    op.drop_column("download_client_configs", "remote_path")
