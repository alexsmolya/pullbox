"""add import ingest policy snapshot

Revision ID: b4c5d6e7f890
Revises: a3b4c5d6e789
Create Date: 2026-05-29
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "b4c5d6e7f890"
down_revision: str | Sequence[str] | None = "a3b4c5d6e789"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("import_jobs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "ingest_policy_snapshot",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            )
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("import_jobs") as batch_op:
        batch_op.drop_column("ingest_policy_snapshot")
