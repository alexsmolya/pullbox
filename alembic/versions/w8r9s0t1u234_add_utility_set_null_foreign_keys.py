"""add utility set-null foreign keys

Revision ID: w8r9s0t1u234
Revises: v7q8r9s0t123
Create Date: 2026-05-15 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "w8r9s0t1u234"
down_revision: str | Sequence[str] | None = "v7q8r9s0t123"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NAMING_CONVENTION = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
}


def _fk_name(table_name: str, column_name: str, referred_table: str) -> str:
    """Return the reflected FK name or Alembic's batch naming-convention name."""
    inspector = sa.inspect(op.get_bind())
    for foreign_key in inspector.get_foreign_keys(table_name):
        if (
            foreign_key.get("constrained_columns") == [column_name]
            and foreign_key.get("referred_table") == referred_table
        ):
            reflected_name = foreign_key.get("name")
            if reflected_name:
                return str(reflected_name)
    return f"fk_{table_name}_{column_name}_{referred_table}"


def _replace_fk(
    *,
    table_name: str,
    column_name: str,
    referred_table: str,
    ondelete: str | None,
) -> None:
    constraint_name = f"fk_{table_name}_{column_name}_{referred_table}"
    existing_name = _fk_name(table_name, column_name, referred_table)
    with op.batch_alter_table(
        table_name,
        naming_convention=_NAMING_CONVENTION,
    ) as batch_op:
        batch_op.drop_constraint(existing_name, type_="foreignkey")
        batch_op.create_foreign_key(
            constraint_name,
            referred_table,
            [column_name],
            ["id"],
            ondelete=ondelete,
        )


def upgrade() -> None:
    """Make nullable utility references clear themselves on target deletion."""
    _replace_fk(
        table_name="utility_jobs",
        column_name="parent_job_id",
        referred_table="utility_jobs",
        ondelete="SET NULL",
    )
    _replace_fk(
        table_name="utility_job_logs",
        column_name="item_id",
        referred_table="utility_job_items",
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Restore previous utility FK behavior without explicit on-delete actions."""
    _replace_fk(
        table_name="utility_job_logs",
        column_name="item_id",
        referred_table="utility_job_items",
        ondelete=None,
    )
    _replace_fk(
        table_name="utility_jobs",
        column_name="parent_job_id",
        referred_table="utility_jobs",
        ondelete=None,
    )
