"""seed backup configuration keys

Revision ID: f1a5c3d89b47
Revises: d8f4a2b67e12
Create Date: 2026-03-01 04:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1a5c3d89b47"
down_revision: str | Sequence[str] | None = "d8f4a2b67e12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BACKUP_KEYS = [
    {"key": "backup_dir", "value": "/data/backups", "value_type": "string"},
    {"key": "backup_interval_days", "value": "7", "value_type": "int"},
    {"key": "backup_retention_days", "value": "28", "value_type": "int"},
]


def upgrade() -> None:
    """Seed backup SystemConfig entries (skip if already present)."""
    conn = op.get_bind()
    system_config = sa.table(
        "system_config",
        sa.column("key", sa.String),
        sa.column("value", sa.Text),
        sa.column("value_type", sa.String),
    )
    for entry in BACKUP_KEYS:
        exists = conn.execute(
            sa.select(system_config.c.key).where(system_config.c.key == entry["key"])
        ).first()
        if not exists:
            conn.execute(system_config.insert().values(**entry))


def downgrade() -> None:
    """Remove backup SystemConfig entries."""
    system_config = sa.table("system_config", sa.column("key", sa.String))
    for entry in BACKUP_KEYS:
        op.execute(system_config.delete().where(system_config.c.key == entry["key"]))
