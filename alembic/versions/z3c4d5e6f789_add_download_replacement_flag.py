"""Add download replacement intent flag.

Revision ID: z3c4d5e6f789
Revises: j2k3l4m5n678
Create Date: 2026-06-25 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "z3c4d5e6f789"
down_revision: str | Sequence[str] | None = "j2k3l4m5n678"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "download_history",
        sa.Column(
            "replace_existing_file",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("download_history", "replace_existing_file")
