"""add whats new release cache

Revision ID: z2a3b4c5d678
Revises: y1z2a3b4c567
Create Date: 2026-05-16
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "z2a3b4c5d678"
down_revision: str | Sequence[str] | None = "y1z2a3b4c567"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "whats_new_release_cache",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("cache_key", sa.String(length=255), nullable=False),
        sa.Column(
            "cache_kind",
            sa.Enum("CURRENT_WEEK", "UPCOMING", name="whatsnewcachekind"),
            nullable=False,
        ),
        sa.Column("store_date", sa.Date(), nullable=True),
        sa.Column("publisher", sa.String(length=255), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_successful_refresh_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cache_key", name="uq_whats_new_release_cache_key"),
    )
    op.create_index(
        "ix_whats_new_release_cache_kind",
        "whats_new_release_cache",
        ["cache_kind"],
    )
    op.create_index(
        "ix_whats_new_release_cache_fetched_at",
        "whats_new_release_cache",
        ["fetched_at"],
    )
    op.create_index(
        "ix_whats_new_release_cache_last_success",
        "whats_new_release_cache",
        ["last_successful_refresh_at"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_whats_new_release_cache_last_success", table_name="whats_new_release_cache")
    op.drop_index("ix_whats_new_release_cache_fetched_at", table_name="whats_new_release_cache")
    op.drop_index("ix_whats_new_release_cache_kind", table_name="whats_new_release_cache")
    op.drop_table("whats_new_release_cache")
