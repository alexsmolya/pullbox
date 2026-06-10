"""add download client option columns

Revision ID: 085ebdab96ee
Revises: a31647518d7f
Create Date: 2026-03-12 17:30:35.803040

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "085ebdab96ee"
down_revision: str | Sequence[str] | None = "a31647518d7f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add SABnzbd and qBittorrent option columns to download_client_configs."""
    op.add_column(
        "download_client_configs", sa.Column("sab_priority", sa.String(length=20), nullable=True)
    )
    op.add_column(
        "download_client_configs",
        sa.Column("sab_post_processing", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "download_client_configs",
        sa.Column("qbt_content_layout", sa.String(length=30), nullable=True),
    )
    op.add_column(
        "download_client_configs", sa.Column("qbt_ratio_limit", sa.Float(), nullable=True)
    )
    op.add_column(
        "download_client_configs", sa.Column("qbt_seeding_time_limit", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    """Remove SABnzbd and qBittorrent option columns."""
    op.drop_column("download_client_configs", "qbt_seeding_time_limit")
    op.drop_column("download_client_configs", "qbt_ratio_limit")
    op.drop_column("download_client_configs", "qbt_content_layout")
    op.drop_column("download_client_configs", "sab_post_processing")
    op.drop_column("download_client_configs", "sab_priority")
