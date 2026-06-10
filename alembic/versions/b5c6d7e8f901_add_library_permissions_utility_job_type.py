"""Add library permissions utility job type.

Revision ID: b5c6d7e8f901
Revises: a4b5c6d7e890
Create Date: 2026-05-16
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "b5c6d7e8f901"
down_revision: str | Sequence[str] | None = "a4b5c6d7e890"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_JOB_TYPES = (
    "file_convert",
    "mass_convert_pipeline",
    "mass_rename",
    "db_check_cleanup",
    "export_library",
    "integrity_check",
    "rollback",
)

_NEW_JOB_TYPES = (
    "file_convert",
    "mass_convert_pipeline",
    "mass_rename",
    "db_check_cleanup",
    "export_library",
    "integrity_check",
    "library_permissions",
    "rollback",
)


def _check_in(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({quoted})"


def _replace_job_type_constraint(values: tuple[str, ...]) -> None:
    with op.batch_alter_table("utility_jobs") as batch_op:
        batch_op.drop_constraint("ck_utility_jobs_job_type", type_="check")
        batch_op.create_check_constraint(
            "ck_utility_jobs_job_type",
            _check_in("job_type", values),
        )


def upgrade() -> None:
    """Allow recursive library permission jobs in the utility queue."""
    _replace_job_type_constraint(_NEW_JOB_TYPES)


def downgrade() -> None:
    """Remove recursive library permission jobs from the utility queue."""
    _replace_job_type_constraint(_OLD_JOB_TYPES)
