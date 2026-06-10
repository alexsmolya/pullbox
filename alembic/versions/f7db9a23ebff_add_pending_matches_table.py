"""add pending_matches table

Revision ID: f7db9a23ebff
Revises: ac5fb574b450
Create Date: 2026-03-03 18:03:53.946885

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f7db9a23ebff"
down_revision: str | Sequence[str] | None = "ac5fb574b450"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "pending_matches",
        sa.Column("issue_id", sa.Integer(), nullable=False),
        sa.Column("release_title", sa.String(length=500), nullable=False),
        sa.Column("download_url", sa.Text(), nullable=False),
        sa.Column("indexer_id", sa.Integer(), nullable=True),
        sa.Column("is_torrent", sa.Boolean(), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("confidence", sa.String(length=20), nullable=False),
        sa.Column("match_details", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(length=50), nullable=True),
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
        sa.ForeignKeyConstraint(["indexer_id"], ["indexer_configs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["issue_id"], ["issues.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("issue_id", "download_url", name="uq_pending_issue_url"),
    )
    op.create_index("ix_pending_created", "pending_matches", ["created_at"], unique=False)
    op.create_index("ix_pending_issue", "pending_matches", ["issue_id"], unique=False)
    op.create_index("ix_pending_status", "pending_matches", ["status"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_pending_status", table_name="pending_matches")
    op.drop_index("ix_pending_issue", table_name="pending_matches")
    op.drop_index("ix_pending_created", table_name="pending_matches")
    op.drop_table("pending_matches")
