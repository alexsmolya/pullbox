"""seed scoring and matching config

Revision ID: e23015086078
Revises: d12904975967
Create Date: 2026-03-01 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e23015086078"
down_revision: str | Sequence[str] | None = "d12904975967"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KEYS = [
    ("score_weight_priority", "40", "int"),
    ("score_weight_age", "30", "int"),
    ("score_weight_size", "20", "int"),
    ("score_weight_format", "10", "int"),
    ("score_confidence_blend", "40", "int"),
    ("match_fuzzy_high_threshold", "85", "int"),
    ("match_fuzzy_low_threshold", "70", "int"),
    ("match_year_tolerance", "1", "int"),
]


def upgrade() -> None:
    """Seed scoring and matching config entries."""
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
    """Remove scoring and matching config entries."""
    system_config = sa.table("system_config", sa.column("key", sa.String))
    for key, _, _ in _KEYS:
        op.execute(system_config.delete().where(system_config.c.key == key))
