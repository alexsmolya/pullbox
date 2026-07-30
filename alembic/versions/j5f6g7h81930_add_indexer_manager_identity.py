"""Add generic indexer-manager identity and availability.

Revision ID: j5f6g7h81930
Revises: i4e5f6g70829
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "j5f6g7h81930"
down_revision: str | None = "i4e5f6g70829"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "indexer_configs",
        sa.Column("manager_indexer_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "indexer_configs",
        sa.Column(
            "manager_available",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )
    op.execute(
        "UPDATE indexer_configs "
        "SET manager_indexer_id = CAST(prowlarr_indexer_id AS VARCHAR) "
        "WHERE source = 'prowlarr' AND prowlarr_indexer_id IS NOT NULL"
    )
    op.create_index(
        "ix_indexer_configs_manager_identity",
        "indexer_configs",
        ["source", "manager_indexer_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_indexer_configs_manager_identity", table_name="indexer_configs")
    op.drop_column("indexer_configs", "manager_available")
    op.drop_column("indexer_configs", "manager_indexer_id")
