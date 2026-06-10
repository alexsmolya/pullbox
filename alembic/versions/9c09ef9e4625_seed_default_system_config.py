"""seed default system config

Revision ID: 9c09ef9e4625
Revises: e4db993bc3df
Create Date: 2026-02-24 13:05:47.725974

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9c09ef9e4625"
down_revision: str | Sequence[str] | None = "e4db993bc3df"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen snapshot of the config keys that existed when this migration was written.
# Later migrations add their own keys — do NOT import DEFAULT_SYSTEM_CONFIG here
# because it grows over time and causes UNIQUE constraint violations.
_INITIAL_CONFIG: list[dict[str, str]] = [
    {"key": "search_interval_hours", "value": "6", "value_type": "int"},
    {"key": "download_poll_interval_seconds", "value": "30", "value_type": "int"},
    {"key": "process_completed_interval_seconds", "value": "60", "value_type": "int"},
    {"key": "max_download_retries", "value": "3", "value_type": "int"},
    {"key": "metadata_refresh_days", "value": "7", "value_type": "int"},
    {"key": "comicvine_rate_limit_per_second", "value": "1", "value_type": "int"},
    {"key": "library_scan_interval_hours", "value": "24", "value_type": "int"},
    {"key": "history_retention_days", "value": "90", "value_type": "int"},
    {"key": "indexer_failure_threshold", "value": "3", "value_type": "int"},
    {"key": "min_release_size_mb", "value": "50", "value_type": "int"},
    {"key": "max_release_size_mb", "value": "2000", "value_type": "int"},
    {"key": "min_quality_score", "value": "10", "value_type": "int"},
    {"key": "preferred_format", "value": "cbz", "value_type": "string"},
    {
        "key": "allowed_import_extensions",
        "value": ".cbr,.cbz,.cb7,.cbt,.pdf,.epub",
        "value_type": "string",
    },
    {"key": "block_dangerous_files", "value": "true", "value_type": "bool"},
    {"key": "archive_size_limit_mb", "value": "2000", "value_type": "int"},
]


def upgrade() -> None:
    """Seed default SystemConfig entries."""
    system_config = sa.table(
        "system_config",
        sa.column("key", sa.String),
        sa.column("value", sa.Text),
        sa.column("value_type", sa.String),
    )
    op.bulk_insert(system_config, _INITIAL_CONFIG)


def downgrade() -> None:
    """Remove seeded SystemConfig entries."""
    system_config = sa.table("system_config", sa.column("key", sa.String))
    for entry in _INITIAL_CONFIG:
        op.execute(system_config.delete().where(system_config.c.key == entry["key"]))
