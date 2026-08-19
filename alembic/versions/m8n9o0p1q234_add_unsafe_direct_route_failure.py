"""Add unsafe direct-route failure classification.

Revision ID: m8n9o0p1q234
Revises: l7m8n9o0p123
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "m8n9o0p1q234"
down_revision: str | None = "l7m8n9o0p123"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("direct_acquisition_attempts", "direct_artifact_attempts")
_CONSTRAINT_NAME = "directartifactfailureclass"
_SQLITE_ARTIFACT_BACKUP = "_direct_artifact_attempts_failure_backup"
_OLD_VALUES = (
    "provider_unavailable",
    "transient_source",
    "transient_host",
    "permanent_mirror",
    "unsupported_artifact_host",
    "artifact_host_auth_required",
    "artifact_host_challenge",
    "host_quota",
    "candidate_invalid",
    "resolver",
    "safety",
    "post_process",
    "user_action",
)
_NEW_VALUES = (*_OLD_VALUES[:10], "unsafe_route", *_OLD_VALUES[10:])


def _constraint_sql(values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"failure_class IN ({quoted})"


def _replace_constraints(values: tuple[str, ...]) -> None:
    bind = op.get_bind()
    sqlite = bind.dialect.name == "sqlite"
    if sqlite:
        op.execute(
            sa.text(
                f"CREATE TEMPORARY TABLE {_SQLITE_ARTIFACT_BACKUP} "
                "AS SELECT * FROM direct_artifact_attempts"
            )
        )
    try:
        # Rebuild the child first so restored rows accept the expanded value set.
        for table in reversed(_TABLES):
            with op.batch_alter_table(table) as batch_op:
                batch_op.drop_constraint(_CONSTRAINT_NAME, type_="check")
                batch_op.create_check_constraint(_CONSTRAINT_NAME, _constraint_sql(values))
        if sqlite:
            # Rebuilding the parent can cascade-delete children when SQLite FK
            # enforcement is active, so restore the exact pre-migration rows.
            op.execute(sa.text("DELETE FROM direct_artifact_attempts"))
            op.execute(
                sa.text(
                    f"INSERT INTO direct_artifact_attempts SELECT * FROM {_SQLITE_ARTIFACT_BACKUP}"
                )
            )
    finally:
        if sqlite:
            op.execute(sa.text(f"DROP TABLE IF EXISTS {_SQLITE_ARTIFACT_BACKUP}"))


def upgrade() -> None:
    _replace_constraints(_NEW_VALUES)
    for table in _TABLES:
        op.execute(
            sa.text(
                f"UPDATE {table} SET failure_class = 'unsafe_route' "
                "WHERE failure_class = 'safety' AND failure_code = 'unsafe_artifact_url'"
            )
        )


def downgrade() -> None:
    for table in _TABLES:
        op.execute(
            sa.text(
                f"UPDATE {table} SET failure_class = 'safety' WHERE failure_class = 'unsafe_route'"
            )
        )
    _replace_constraints(_OLD_VALUES)
