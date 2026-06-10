"""add import materialization audit fields

Revision ID: y1z2a3b4c567
Revises: x9s0t1u2v345
Create Date: 2026-05-15
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "y1z2a3b4c567"
down_revision: str | Sequence[str] | None = "x9s0t1u2v345"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("import_jobs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "torrent_import_strategy",
                sa.String(length=20),
                nullable=False,
                server_default="standard",
            )
        )
        batch_op.add_column(
            sa.Column(
                "effective_import_strategy",
                sa.String(length=30),
                nullable=False,
                server_default="standard",
            )
        )
        batch_op.add_column(
            sa.Column(
                "effective_transfer_method",
                sa.String(length=20),
                nullable=False,
                server_default="move",
            )
        )
        batch_op.add_column(
            sa.Column(
                "source_preserved",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("import_jobs") as batch_op:
        batch_op.drop_column("source_preserved")
        batch_op.drop_column("effective_transfer_method")
        batch_op.drop_column("effective_import_strategy")
        batch_op.drop_column("torrent_import_strategy")
