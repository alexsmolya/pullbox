"""seed phase e scoring config keys

Revision ID: a3d58599d50d
Revises: 2878182e7522
Create Date: 2026-04-06 11:54:02.695505

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3d58599d50d"
down_revision: str | Sequence[str] | None = "2878182e7522"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KEYS = [
    ("score_weight_grabs", "0", "int"),
    ("score_penalty_pack", "-20", "int"),
    ("preferred_language", "en", "string"),
    ("score_bonus_digital", "10", "int"),
    ("max_file_count", "5", "int"),
]


def upgrade() -> None:
    """Seed Phase E scoring config entries."""
    system_config = sa.table(
        "system_config",
        sa.column("key", sa.String),
        sa.column("value", sa.Text),
        sa.column("value_type", sa.String),
    )
    op.bulk_insert(
        system_config,
        [{"key": k, "value": v, "value_type": vt} for k, v, vt in _KEYS],
    )


def downgrade() -> None:
    """Remove Phase E scoring config entries."""
    system_config = sa.table("system_config", sa.column("key", sa.String))
    for key, _, _ in _KEYS:
        op.execute(system_config.delete().where(system_config.c.key == key))
