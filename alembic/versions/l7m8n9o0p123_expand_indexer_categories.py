"""Expand indexer categories for manager capability lists.

Revision ID: l7m8n9o0p123
Revises: k6g7h8i9j012
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "l7m8n9o0p123"
down_revision: str | None = "k6g7h8i9j012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("indexer_configs") as batch_op:
        batch_op.alter_column(
            "categories",
            existing_type=sa.String(length=255),
            type_=sa.Text(),
            existing_nullable=True,
        )


def downgrade() -> None:
    # The legacy column cannot represent manager lists longer than 255 characters.
    op.execute(
        "UPDATE indexer_configs SET categories = substr(categories, 1, 255) "
        "WHERE length(categories) > 255"
    )
    with op.batch_alter_table("indexer_configs") as batch_op:
        batch_op.alter_column(
            "categories",
            existing_type=sa.Text(),
            type_=sa.String(length=255),
            existing_nullable=True,
        )
