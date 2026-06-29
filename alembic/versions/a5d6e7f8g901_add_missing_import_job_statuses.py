"""Add missing import job status enum values.

Revision ID: a5d6e7f8g901
Revises: z3c4d5e6f789
Create Date: 2026-06-29
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "a5d6e7f8g901"
down_revision: str | Sequence[str] | None = "z3c4d5e6f789"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE importjobstatus ADD VALUE IF NOT EXISTS 'PAUSING'")
        op.execute("ALTER TYPE importjobstatus ADD VALUE IF NOT EXISTS 'FILE_MATCHING'")
        op.execute("ALTER TYPE importjobstatus ADD VALUE IF NOT EXISTS 'STALLED'")
        op.execute("ALTER TYPE importjobstatus ADD VALUE IF NOT EXISTS 'CANCELLING'")
        op.execute("ALTER TYPE importjobstatus ADD VALUE IF NOT EXISTS 'ROLLING_BACK'")
        op.execute("ALTER TYPE importjobstatus ADD VALUE IF NOT EXISTS 'ROLLED_BACK'")


def downgrade() -> None:
    """Downgrade schema."""
    # PostgreSQL enum value removal is intentionally omitted.
    pass
