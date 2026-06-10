"""Add issue catalog last checked timestamp.

Revision ID: i1j2k3l4m567
Revises: h0i1j2k3l456
Create Date: 2026-06-05
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "i1j2k3l4m567"
down_revision: str | Sequence[str] | None = "h0i1j2k3l456"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("series") as batch_op:
        batch_op.add_column(
            sa.Column(
                "issue_catalog_last_checked_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )

    op.execute(
        sa.text(
            """
            UPDATE series
            SET issue_catalog_last_checked_at = issue_catalog_last_synced_at
            WHERE issue_catalog_last_synced_at IS NOT NULL
            """
        )
    )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("series") as batch_op:
        batch_op.drop_column("issue_catalog_last_checked_at")
