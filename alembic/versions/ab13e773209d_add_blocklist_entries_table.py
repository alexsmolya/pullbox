"""add blocklist_entries table

Revision ID: ab13e773209d
Revises: b1c2d3e4f567
Create Date: 2026-03-20 14:56:48.913265

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ab13e773209d"
down_revision: str | Sequence[str] | None = "b1c2d3e4f567"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add blocklist_entries table."""
    op.create_table(
        "blocklist_entries",
        sa.Column("release_title", sa.String(length=500), nullable=False),
        sa.Column("release_title_normalized", sa.String(length=500), nullable=False),
        sa.Column("download_url", sa.String(length=2000), nullable=True),
        sa.Column("series_id", sa.Integer(), nullable=True),
        sa.Column("issue_id", sa.Integer(), nullable=True),
        sa.Column("indexer_id", sa.Integer(), nullable=True),
        sa.Column(
            "reason",
            sa.Enum("FAILED", "REJECTED", "MANUAL", name="blocklistreason"),
            nullable=False,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("release_group", sa.String(length=100), nullable=True),
        sa.Column("download_history_id", sa.Integer(), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["download_history_id"], ["download_history.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["indexer_id"], ["indexer_configs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["issue_id"], ["issues.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["series_id"], ["series.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_blocklist_created", "blocklist_entries", ["created_at"], unique=False)
    op.create_index("ix_blocklist_reason", "blocklist_entries", ["reason"], unique=False)
    op.create_index("ix_blocklist_series", "blocklist_entries", ["series_id"], unique=False)
    op.create_index(
        "ix_blocklist_title_norm", "blocklist_entries", ["release_title_normalized"], unique=True
    )


def downgrade() -> None:
    """Remove blocklist_entries table."""
    op.drop_index("ix_blocklist_title_norm", table_name="blocklist_entries")
    op.drop_index("ix_blocklist_series", table_name="blocklist_entries")
    op.drop_index("ix_blocklist_reason", table_name="blocklist_entries")
    op.drop_index("ix_blocklist_created", table_name="blocklist_entries")
    op.drop_table("blocklist_entries")
