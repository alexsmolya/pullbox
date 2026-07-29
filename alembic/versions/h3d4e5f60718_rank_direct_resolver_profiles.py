"""Rank browser resolver profiles by supported implementation.

Revision ID: h3d4e5f60718
Revises: g2c3d4e5f607
Create Date: 2026-07-29
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "h3d4e5f60718"
down_revision: str | Sequence[str] | None = "g2c3d4e5f607"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


resolver_kind = sa.Enum(
    "flaresolverr",
    "byparr",
    "trawl",
    name="directresolverkind",
    native_enum=False,
    create_constraint=True,
)


def upgrade() -> None:
    """Promote the existing resolver to the first ranked profile."""
    with op.batch_alter_table("direct_resolver_configs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "resolver_kind",
                resolver_kind,
                server_default="flaresolverr",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("priority", sa.Integer(), server_default="10", nullable=False)
        )
        batch_op.create_unique_constraint(
            "uq_direct_resolver_kind",
            ["resolver_kind"],
        )
        batch_op.create_check_constraint(
            "ck_direct_resolver_priority",
            "priority > 0 AND priority <= 1000",
        )


def downgrade() -> None:
    """Return to the original single-profile schema."""
    with op.batch_alter_table("direct_resolver_configs") as batch_op:
        batch_op.drop_constraint("ck_direct_resolver_priority", type_="check")
        batch_op.drop_constraint("uq_direct_resolver_kind", type_="unique")
        batch_op.drop_constraint("directresolverkind", type_="check")
        batch_op.drop_column("priority")
        batch_op.drop_column("resolver_kind")
