"""add search_logs table

Revision ID: 49d9e835fbe2
Revises: f7db9a23ebff
Create Date: 2026-03-05 15:35:11.461130

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "49d9e835fbe2"
down_revision: str | Sequence[str] | None = "f7db9a23ebff"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "search_logs",
        sa.Column("issue_id", sa.Integer(), nullable=False),
        sa.Column("series_title", sa.String(length=500), nullable=False),
        sa.Column("issue_number", sa.Float(), nullable=False),
        sa.Column(
            "search_type",
            sa.Enum("MANUAL", "AUTOMATED", "BULK", name="searchtype"),
            nullable=False,
        ),
        sa.Column("results_found", sa.Integer(), server_default="0", nullable=False),
        sa.Column("results_grabbed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("results_queued", sa.Integer(), server_default="0", nullable=False),
        sa.Column("results_rejected", sa.Integer(), server_default="0", nullable=False),
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
        sa.ForeignKeyConstraint(["issue_id"], ["issues.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_search_logs_created", "search_logs", ["created_at"], unique=False)
    op.create_index("ix_search_logs_type", "search_logs", ["search_type"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_search_logs_type", table_name="search_logs")
    op.drop_index("ix_search_logs_created", table_name="search_logs")
    op.drop_table("search_logs")
