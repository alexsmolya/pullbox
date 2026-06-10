"""Add cover_url column to series and issues tables.

Stores the ComicVine CDN URL so covers can be displayed immediately
from the CDN while local copies are downloaded in the background.

Revision ID: i4d5e6f7g890
Revises: h3c4d5e6f789
Create Date: 2026-03-01
"""

import sqlalchemy as sa

from alembic import op

revision = "i4d5e6f7g890"
down_revision = "e23015086078"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    """Check if a column already exists in the given table (SQLite)."""
    conn = op.get_bind()
    result = conn.execute(sa.text(f"PRAGMA table_info('{table}')"))
    columns = [row[1] for row in result]
    return column in columns


def upgrade() -> None:
    if not _column_exists("series", "cover_url"):
        op.add_column("series", sa.Column("cover_url", sa.String(500), nullable=True))
    if not _column_exists("issues", "cover_url"):
        op.add_column("issues", sa.Column("cover_url", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("issues", "cover_url")
    op.drop_column("series", "cover_url")
