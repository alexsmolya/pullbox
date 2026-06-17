"""simplify_monitoring_add_manual_skip

Revision ID: 2878182e7522
Revises: 1b615420d50f
Create Date: 2026-03-24 19:56:25.321631

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2878182e7522"
down_revision: str | Sequence[str] | None = "1b615420d50f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Simplify monitoring: drop monitor_type/range/search_on_add, add manual_skip."""
    # Add manual_skip to issues (default False)
    op.add_column(
        "issues", sa.Column("manual_skip", sa.Boolean(), server_default="0", nullable=False)
    )

    # Drop monitoring columns from series
    op.drop_column("series", "monitor_type")
    op.drop_column("series", "monitor_range_start")
    op.drop_column("series", "monitor_range_end")
    op.drop_column("series", "search_on_add")

    # Replace monitor_type with monitored on import_jobs
    op.add_column(
        "import_jobs", sa.Column("monitored", sa.Boolean(), nullable=False, server_default="0")
    )
    op.drop_column("import_jobs", "monitor_type")


def downgrade() -> None:
    """Reverse: restore monitor_type/range/search_on_add, drop manual_skip."""
    # Restore import_jobs.monitor_type
    op.add_column(
        "import_jobs",
        sa.Column("monitor_type", sa.VARCHAR(length=50), nullable=False, server_default="none"),
    )
    op.drop_column("import_jobs", "monitored")

    # Restore series columns
    op.add_column(
        "series",
        sa.Column("search_on_add", sa.BOOLEAN(), server_default=sa.text("'0'"), nullable=False),
    )
    op.add_column(
        "series",
        sa.Column("monitor_type", sa.VARCHAR(length=8), nullable=False, server_default="none"),
    )
    op.add_column("series", sa.Column("monitor_range_start", sa.FLOAT(), nullable=True))
    op.add_column("series", sa.Column("monitor_range_end", sa.FLOAT(), nullable=True))

    # Drop manual_skip
    op.drop_column("issues", "manual_skip")
