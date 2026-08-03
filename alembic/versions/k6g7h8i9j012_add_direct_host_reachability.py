"""Add artifact-host reachability and operational outcomes.

Revision ID: k6g7h8i9j012
Revises: j5f6g7h81930
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "k6g7h8i9j012"
down_revision: str | None = "j5f6g7h81930"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum(enum_name: str, *values: str) -> sa.Enum:
    return sa.Enum(
        *values,
        name=enum_name,
        native_enum=False,
        create_constraint=True,
    )


def upgrade() -> None:
    reachability_state = _enum(
        "directhostreachabilitystate",
        "not_checked",
        "reachable",
        "not_reachable",
        "authentication_required",
        "quota_limited",
        "unavailable",
    )
    operational_result = _enum(
        "directhostoperationalresult",
        "successful",
        "failed",
    )
    with op.batch_alter_table("direct_host_configs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "reachability_state",
                reachability_state,
                nullable=False,
                server_default="not_checked",
            )
        )
        batch_op.add_column(
            sa.Column("last_reachable_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(sa.Column("last_operational_result", operational_result, nullable=True))
        batch_op.add_column(
            sa.Column("last_operational_at", sa.DateTime(timezone=True), nullable=True)
        )

    op.execute(
        "UPDATE direct_host_configs "
        "SET reachability_state = CASE account_state "
        "WHEN 'healthy' THEN 'reachable' "
        "WHEN 'authentication_required' THEN 'authentication_required' "
        "WHEN 'quota_limited' THEN 'quota_limited' "
        "WHEN 'unavailable' THEN 'unavailable' "
        "ELSE 'not_checked' END, "
        "last_reachable_at = CASE WHEN account_state = 'healthy' THEN last_tested_at ELSE NULL END"
    )


def downgrade() -> None:
    with op.batch_alter_table("direct_host_configs") as batch_op:
        batch_op.drop_constraint("directhostoperationalresult", type_="check")
        batch_op.drop_constraint("directhostreachabilitystate", type_="check")
        batch_op.drop_column("last_operational_at")
        batch_op.drop_column("last_operational_result")
        batch_op.drop_column("last_reachable_at")
        batch_op.drop_column("reachability_state")
