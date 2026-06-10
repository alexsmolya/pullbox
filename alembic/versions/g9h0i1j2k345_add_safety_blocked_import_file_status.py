"""Add safety-blocked import-file status.

Revision ID: g9h0i1j2k345
Revises: f8g9h0i1j234
Create Date: 2026-06-01
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "g9h0i1j2k345"
down_revision: str | Sequence[str] | None = "f8g9h0i1j234"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE importedfilestatus ADD VALUE IF NOT EXISTS 'SAFETY_BLOCKED'")


def downgrade() -> None:
    """Downgrade schema."""
    # PostgreSQL enum value removal is intentionally omitted.
    pass
