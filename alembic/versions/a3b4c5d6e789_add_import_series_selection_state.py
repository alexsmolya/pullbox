"""add import series selection state

Revision ID: a3b4c5d6e789
Revises: z2a3b4c5d678, c6d7e8f9a012
Create Date: 2026-05-22
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "a3b4c5d6e789"
down_revision: str | Sequence[str] | None = ("z2a3b4c5d678", "c6d7e8f9a012")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("import_series") as batch_op:
        batch_op.add_column(
            sa.Column(
                "selected_for_import",
                sa.Boolean(),
                nullable=False,
                server_default="0",
            )
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("import_series") as batch_op:
        batch_op.drop_column("selected_for_import")
