"""Add manual Torznab browser-resolver opt-in.

Revision ID: i4e5f6g70829
Revises: h3d4e5f60718
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "i4e5f6g70829"
down_revision: str | None = "h3d4e5f60718"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "indexer_configs",
        sa.Column(
            "resolver_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    op.drop_column("indexer_configs", "resolver_enabled")
