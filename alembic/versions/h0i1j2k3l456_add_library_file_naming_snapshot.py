"""Add library file naming snapshot.

Revision ID: h0i1j2k3l456
Revises: g9h0i1j2k345
Create Date: 2026-06-03
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "h0i1j2k3l456"
down_revision: str | Sequence[str] | None = "g9h0i1j2k345"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("library_files") as batch_op:
        batch_op.add_column(
            sa.Column(
                "naming_snapshot",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            )
        )

    _backfill_series_paths_from_library_files()


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("library_files") as batch_op:
        batch_op.drop_column("naming_snapshot")


def _backfill_series_paths_from_library_files() -> None:
    """Populate missing series paths from already tracked library files."""
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT
                s.id AS series_id,
                s.library_root_id AS series_library_root_id,
                lf.library_root_id AS file_library_root_id,
                lf.file_path AS file_path
            FROM series s
            JOIN issues i ON i.series_id = s.id
            JOIN library_files lf ON lf.issue_id = i.id
            WHERE (s.path IS NULL OR s.path = '')
              AND lf.file_path IS NOT NULL
            ORDER BY s.id, lf.file_path
            """
        )
    ).mappings()

    seen_series_ids: set[int] = set()
    for row in rows:
        series_id = int(row["series_id"])
        if series_id in seen_series_ids:
            continue
        seen_series_ids.add(series_id)

        series_folder = str(Path(str(row["file_path"])).parent)
        values: dict[str, object] = {"path": series_folder, "series_id": series_id}
        library_root_id = row["series_library_root_id"] or row["file_library_root_id"]
        update_sql = "UPDATE series SET path = :path"
        if library_root_id is not None:
            update_sql += ", library_root_id = COALESCE(library_root_id, :library_root_id)"
            values["library_root_id"] = library_root_id
        update_sql += " WHERE id = :series_id"
        bind.execute(sa.text(update_sql), values)
