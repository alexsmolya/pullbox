"""Add dashboard intelligence rollup tables.

Revision ID: 5f4a3c2b1d90
Revises: a3d58599d50d
Create Date: 2026-04-08
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "5f4a3c2b1d90"
down_revision: str | Sequence[str] | None = "a3d58599d50d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create dashboard rollup and storage snapshot tables."""
    op.create_table(
        "dashboard_metric_rollups",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("metric_key", sa.String(length=100), nullable=False),
        sa.Column("bucket_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("bucket_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column(
            "context_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "metric_key",
            "bucket_start",
            name="uq_dashboard_metric_rollups_key",
        ),
    )
    op.create_index(
        "ix_dashboard_metric_rollups_metric_bucket",
        "dashboard_metric_rollups",
        ["metric_key", "bucket_start"],
    )

    op.create_table(
        "dashboard_storage_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("source_path", sa.String(length=1000), nullable=False),
        sa.Column("total_bytes", sa.BigInteger(), nullable=False),
        sa.Column("used_bytes", sa.BigInteger(), nullable=False),
        sa.Column("free_bytes", sa.BigInteger(), nullable=False),
        sa.Column("used_percent", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "snapshot_date",
            name="uq_dashboard_storage_snapshots_date",
        ),
    )
    op.create_index(
        "ix_dashboard_storage_snapshots_snapshot_date",
        "dashboard_storage_snapshots",
        ["snapshot_date"],
    )


def downgrade() -> None:
    """Drop dashboard rollup and storage snapshot tables."""
    op.drop_index(
        "ix_dashboard_storage_snapshots_snapshot_date",
        table_name="dashboard_storage_snapshots",
    )
    op.drop_table("dashboard_storage_snapshots")

    op.drop_index(
        "ix_dashboard_metric_rollups_metric_bucket",
        table_name="dashboard_metric_rollups",
    )
    op.drop_table("dashboard_metric_rollups")
