"""Add import workflow runtime fields.

Revision ID: c6d7e8f9a012
Revises: a4b5c6d7e8f9
Create Date: 2026-05-21 19:55:00.000000
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "c6d7e8f9a012"
down_revision: str | Sequence[str] | None = "a4b5c6d7e8f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONTROL_REQUEST_ENUM = sa.Enum("none", "pause", "cancel", name="importcontrolrequest")


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        _CONTROL_REQUEST_ENUM.create(bind, checkfirst=True)

    with op.batch_alter_table("import_jobs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "progress_revision",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(
            sa.Column(
                "control_request",
                _CONTROL_REQUEST_ENUM,
                nullable=False,
                server_default="none",
            )
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("import_jobs") as batch_op:
        batch_op.drop_column("control_request")
        batch_op.drop_column("progress_revision")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        _CONTROL_REQUEST_ENUM.drop(bind, checkfirst=True)
