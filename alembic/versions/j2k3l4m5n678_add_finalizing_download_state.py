"""Add finalizing download state.

Revision ID: j2k3l4m5n678
Revises: i1j2k3l4m567
Create Date: 2026-06-19
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "j2k3l4m5n678"
down_revision: str | Sequence[str] | None = "i1j2k3l4m567"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE downloadstate ADD VALUE IF NOT EXISTS 'FINALIZING'")


def downgrade() -> None:
    """Downgrade schema."""
    # PostgreSQL enum value removal is intentionally omitted.
    pass
