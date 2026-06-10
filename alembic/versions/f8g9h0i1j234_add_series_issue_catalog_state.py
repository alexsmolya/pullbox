"""Add series issue catalog state.

Revision ID: f8g9h0i1j234
Revises: e7f8g9h0i123
Create Date: 2026-06-01
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "f8g9h0i1j234"
down_revision: str | Sequence[str] | None = "e7f8g9h0i123"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ISSUE_CATALOG_STATE_ENUM = sa.Enum(
    "COMPLETE",
    "PARTIAL",
    "HYDRATING",
    "FAILED",
    name="issuecatalogstate",
)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        _ISSUE_CATALOG_STATE_ENUM.create(bind, checkfirst=True)

    with op.batch_alter_table("series") as batch_op:
        batch_op.add_column(
            sa.Column(
                "issue_catalog_state",
                _ISSUE_CATALOG_STATE_ENUM,
                nullable=False,
                server_default="COMPLETE",
            )
        )
        batch_op.add_column(
            sa.Column(
                "issue_catalog_last_synced_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )
        batch_op.add_column(sa.Column("issue_catalog_error", sa.Text(), nullable=True))
        batch_op.create_index(
            "ix_series_issue_catalog_state",
            ["issue_catalog_state"],
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("series") as batch_op:
        batch_op.drop_index("ix_series_issue_catalog_state")
        batch_op.drop_column("issue_catalog_error")
        batch_op.drop_column("issue_catalog_last_synced_at")
        batch_op.drop_column("issue_catalog_state")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        _ISSUE_CATALOG_STATE_ENUM.drop(bind, checkfirst=True)
