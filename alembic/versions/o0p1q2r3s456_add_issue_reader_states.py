"""Add private per-user embedded reader state.

Revision ID: o0p1q2r3s456
Revises: n9o0p1q2r345
Create Date: 2026-08-03
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "o0p1q2r3s456"
down_revision: str | None = "n9o0p1q2r345"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "issue_reader_states",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("issue_id", sa.Integer(), nullable=False),
        sa.Column("last_page_index", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("content_revision", sa.String(length=64), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "id",
            sa.Integer(),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["issue_id"], ["issues.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "issue_id", name="uq_issue_reader_state_user_issue"),
    )
    op.create_index(
        "ix_issue_reader_states_issue",
        "issue_reader_states",
        ["issue_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_issue_reader_states_issue", table_name="issue_reader_states")
    op.drop_table("issue_reader_states")
