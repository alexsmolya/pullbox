"""seed post_processing_method config

Revision ID: a3f7b1c82d01
Revises: 9c09ef9e4625
Create Date: 2026-02-24 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3f7b1c82d01"
down_revision: str | Sequence[str] | None = "9c09ef9e4625"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Seed post_processing_method SystemConfig entry."""
    system_config = sa.table(
        "system_config",
        sa.column("key", sa.String),
        sa.column("value", sa.Text),
        sa.column("value_type", sa.String),
    )
    op.bulk_insert(
        system_config,
        [{"key": "post_processing_method", "value": "move", "value_type": "string"}],
    )


def downgrade() -> None:
    """Remove post_processing_method SystemConfig entry."""
    system_config = sa.table("system_config", sa.column("key", sa.String))
    op.execute(system_config.delete().where(system_config.c.key == "post_processing_method"))
