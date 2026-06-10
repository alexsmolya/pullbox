"""add_import_files_table

Revision ID: a31647518d7f
Revises: f2a7c8d3e4b5
Create Date: 2026-03-11 10:53:22.534167

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a31647518d7f"
down_revision: str | Sequence[str] | None = "f2a7c8d3e4b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create import_files table
    op.create_table(
        "import_files",
        sa.Column("import_job_id", sa.Integer(), nullable=False),
        sa.Column("import_series_id", sa.Integer(), nullable=False),
        sa.Column("file_path", sa.String(length=1000), nullable=False),
        sa.Column("file_name", sa.String(length=500), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("file_format", sa.String(length=10), nullable=False),
        sa.Column("parsed_series", sa.String(length=500), nullable=True),
        sa.Column("parsed_issue_number", sa.Float(), nullable=True),
        sa.Column("parsed_year", sa.Integer(), nullable=True),
        sa.Column("has_comicinfo", sa.Boolean(), nullable=False),
        sa.Column("comicvine_issue_id", sa.Integer(), nullable=True),
        sa.Column("issue_number_raw", sa.String(length=50), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "MATCHED",
                "CONFLICT",
                "NO_MATCH",
                "CONFIRMED",
                "SKIPPED",
                "IMPORTED",
                "FAILED",
                name="importedfilestatus",
            ),
            nullable=False,
        ),
        sa.Column("matched_issue_id", sa.Integer(), nullable=True),
        sa.Column("match_confidence", sa.String(length=20), nullable=True),
        sa.Column("match_method", sa.String(length=50), nullable=True),
        sa.Column("conflict_group_id", sa.Integer(), nullable=True),
        sa.Column("is_preferred", sa.Boolean(), nullable=False),
        sa.Column("library_file_id", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["import_job_id"], ["import_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["import_series_id"], ["import_series.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["library_file_id"], ["library_files.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["matched_issue_id"], ["issues.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_import_files_job_series",
        "import_files",
        ["import_job_id", "import_series_id"],
        unique=False,
    )

    # Add file-level counters to import_jobs
    op.add_column(
        "import_jobs",
        sa.Column("total_files_found", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "import_jobs",
        sa.Column("total_files_matched", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "import_jobs",
        sa.Column("total_files_conflict", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "import_jobs",
        sa.Column("total_files_no_match", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "import_jobs",
        sa.Column("total_files_imported", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "import_jobs",
        sa.Column("total_files_failed", sa.Integer(), nullable=False, server_default="0"),
    )

    # Add file-level counters to import_series
    op.add_column(
        "import_series",
        sa.Column("files_total", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "import_series",
        sa.Column("files_matched", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "import_series",
        sa.Column("files_conflict", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "import_series",
        sa.Column("files_no_match", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "import_series",
        sa.Column("files_imported", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "import_series",
        sa.Column("files_failed", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("import_series", "files_failed")
    op.drop_column("import_series", "files_imported")
    op.drop_column("import_series", "files_no_match")
    op.drop_column("import_series", "files_conflict")
    op.drop_column("import_series", "files_matched")
    op.drop_column("import_series", "files_total")
    op.drop_column("import_jobs", "total_files_failed")
    op.drop_column("import_jobs", "total_files_imported")
    op.drop_column("import_jobs", "total_files_no_match")
    op.drop_column("import_jobs", "total_files_conflict")
    op.drop_column("import_jobs", "total_files_matched")
    op.drop_column("import_jobs", "total_files_found")
    op.drop_index("ix_import_files_job_series", table_name="import_files")
    op.drop_table("import_files")
