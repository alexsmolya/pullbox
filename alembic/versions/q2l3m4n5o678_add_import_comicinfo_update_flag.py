"""add import ComicInfo update flag

Revision ID: q2l3m4n5o678
Revises: p1k2l3m4n567
Create Date: 2026-04-30 16:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "q2l3m4n5o678"
down_revision: str | Sequence[str] | None = "p1k2l3m4n567"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("import_jobs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "update_embedded_comicinfo_from_match",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("import_jobs") as batch_op:
        batch_op.drop_column("update_embedded_comicinfo_from_match")
