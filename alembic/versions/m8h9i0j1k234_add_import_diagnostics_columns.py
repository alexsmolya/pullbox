"""add import diagnostics columns

Revision ID: m8h9i0j1k234
Revises: l7g8h9i0j123
Create Date: 2026-04-27 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "m8h9i0j1k234"
down_revision: str | Sequence[str] | None = "l7g8h9i0j123"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add structured diagnostics payloads to import rows."""
    op.add_column(
        "import_series",
        sa.Column("diagnostics", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "import_files",
        sa.Column("diagnostics", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    """Remove structured diagnostics payloads from import rows."""
    op.drop_column("import_files", "diagnostics")
    op.drop_column("import_series", "diagnostics")
