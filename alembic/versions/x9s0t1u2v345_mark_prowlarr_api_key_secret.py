"""Mark stored Prowlarr API key config as secret.

Revision ID: x9s0t1u2v345
Revises: w8r9s0t1u234
Create Date: 2026-05-15
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "x9s0t1u2v345"
down_revision: str | Sequence[str] | None = "w8r9s0t1u234"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE system_config
            SET value_type = 'secret'
            WHERE key = 'prowlarr_api_key'
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE system_config
            SET value_type = 'string'
            WHERE key = 'prowlarr_api_key'
            """
        )
    )
