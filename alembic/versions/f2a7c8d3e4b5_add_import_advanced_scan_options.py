"""add import advanced scan options

Revision ID: f2a7c8d3e4b5
Revises: e17c92df151a
Create Date: 2026-03-06 21:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2a7c8d3e4b5"
down_revision: str | Sequence[str] | None = "e17c92df151a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add min_files_per_series and file_formats to import_jobs."""
    op.add_column(
        "import_jobs",
        sa.Column("min_files_per_series", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "import_jobs",
        sa.Column("file_formats", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    """Remove min_files_per_series and file_formats from import_jobs."""
    op.drop_column("import_jobs", "file_formats")
    op.drop_column("import_jobs", "min_files_per_series")
