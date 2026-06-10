"""seed search_ignore_words config

Revision ID: d12904975967
Revises: 119149955c0a
Create Date: 2026-03-01 14:24:14.006365

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d12904975967"
down_revision: str | Sequence[str] | None = "119149955c0a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KEY = "search_ignore_words"
_VALUE = (
    "covers only,cover only,preview,sampler,ashcan,sketch,virgin,incentive,poster,print,blank cover"
)


def upgrade() -> None:
    """Seed search_ignore_words config entry."""
    system_config = sa.table(
        "system_config",
        sa.column("key", sa.String),
        sa.column("value", sa.Text),
        sa.column("value_type", sa.String),
    )
    op.bulk_insert(system_config, [{"key": _KEY, "value": _VALUE, "value_type": "string"}])


def downgrade() -> None:
    """Remove search_ignore_words config entry."""
    system_config = sa.table("system_config", sa.column("key", sa.String))
    op.execute(system_config.delete().where(system_config.c.key == _KEY))
