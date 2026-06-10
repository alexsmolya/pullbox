"""seed logging configuration keys

Revision ID: d8f4a2b67e12
Revises: c7a2d1e5f890
Create Date: 2026-03-01 02:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d8f4a2b67e12"
down_revision: str | Sequence[str] | None = "c7a2d1e5f890"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LOGGING_KEYS = [
    {"key": "log_level", "value": "info", "value_type": "string"},
    {"key": "logs_dir", "value": "/data/logs", "value_type": "string"},
    {"key": "log_size_limit_mb", "value": "1", "value_type": "int"},
    {"key": "log_backup_count", "value": "5", "value_type": "int"},
]


def upgrade() -> None:
    """Seed logging SystemConfig entries (skip if already present)."""
    conn = op.get_bind()
    system_config = sa.table(
        "system_config",
        sa.column("key", sa.String),
        sa.column("value", sa.Text),
        sa.column("value_type", sa.String),
    )
    for entry in LOGGING_KEYS:
        exists = conn.execute(
            sa.select(system_config.c.key).where(system_config.c.key == entry["key"])
        ).first()
        if not exists:
            conn.execute(system_config.insert().values(**entry))


def downgrade() -> None:
    """Remove logging SystemConfig entries."""
    system_config = sa.table("system_config", sa.column("key", sa.String))
    for entry in LOGGING_KEYS:
        op.execute(system_config.delete().where(system_config.c.key == entry["key"]))
