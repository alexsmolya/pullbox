"""add metadata provider cache

Revision ID: c5d6e7f8g901
Revises: b4c5d6e7f890
Create Date: 2026-05-29
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "c5d6e7f8g901"
down_revision: str | Sequence[str] | None = "b4c5d6e7f890"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "metadata_provider_cache",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("provider_name", sa.String(length=50), nullable=False),
        sa.Column("cache_kind", sa.String(length=80), nullable=False),
        sa.Column("cache_key", sa.String(length=128), nullable=False),
        sa.Column("request", sa.JSON(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider_name",
            "cache_kind",
            "cache_key",
            name="uq_metadata_provider_cache_identity",
        ),
    )
    op.create_index(
        "ix_metadata_provider_cache_provider_kind",
        "metadata_provider_cache",
        ["provider_name", "cache_kind"],
    )
    op.create_index(
        "ix_metadata_provider_cache_expires_at",
        "metadata_provider_cache",
        ["expires_at"],
    )
    op.create_index(
        "ix_metadata_provider_cache_fetched_at",
        "metadata_provider_cache",
        ["fetched_at"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_metadata_provider_cache_fetched_at", table_name="metadata_provider_cache")
    op.drop_index("ix_metadata_provider_cache_expires_at", table_name="metadata_provider_cache")
    op.drop_index(
        "ix_metadata_provider_cache_provider_kind",
        table_name="metadata_provider_cache",
    )
    op.drop_table("metadata_provider_cache")
