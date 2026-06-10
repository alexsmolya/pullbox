"""Add series_type, parent_series_id, and matching_suggestions table.

Revision ID: h3c4d5e6f789
Revises: g2b3d4e5f678_series_folders_and_issue_type
Create Date: 2026-03-01
"""

import sqlalchemy as sa

from alembic import op

revision = "h3c4d5e6f789"
down_revision = "g2b3d4e5f678"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    """Check if a column already exists in the given table (SQLite)."""
    conn = op.get_bind()
    result = conn.execute(sa.text(f"PRAGMA table_info('{table}')"))
    return any(row[1] == column for row in result)


def _index_exists(index_name: str) -> bool:
    """Check if an index already exists (SQLite)."""
    conn = op.get_bind()
    result = conn.execute(
        sa.text(f"SELECT 1 FROM sqlite_master WHERE type='index' AND name='{index_name}'")
    )
    return result.first() is not None


def _table_exists(table: str) -> bool:
    """Check if a table already exists (SQLite)."""
    conn = op.get_bind()
    result = conn.execute(
        sa.text(f"SELECT 1 FROM sqlite_master WHERE type='table' AND name='{table}'")
    )
    return result.first() is not None


def upgrade() -> None:
    # Add series_type column to series table
    if not _column_exists("series", "series_type"):
        op.add_column(
            "series",
            sa.Column(
                "series_type",
                sa.Enum(
                    "STANDARD",
                    "ANNUAL",
                    "TPB",
                    "OMNIBUS",
                    "GRAPHIC_NOVEL",
                    "HARDCOVER",
                    "ONE_SHOT",
                    "SPECIAL",
                    "COMPENDIUM",
                    "DELUXE",
                    name="seriestype",
                ),
                nullable=False,
                server_default="STANDARD",
            ),
        )
    if not _index_exists("ix_series_series_type"):
        op.create_index("ix_series_series_type", "series", ["series_type"])

    # Add parent_series_id column (skip if already present from partial run)
    if not _column_exists("series", "parent_series_id"):
        op.add_column(
            "series",
            sa.Column("parent_series_id", sa.Integer(), nullable=True),
        )
    if not _index_exists("ix_series_parent_series_id"):
        op.create_index("ix_series_parent_series_id", "series", ["parent_series_id"])

    # Create matching_suggestions table (skip if already exists)
    if _table_exists("matching_suggestions"):
        return
    op.create_table(
        "matching_suggestions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "library_file_id",
            sa.Integer(),
            sa.ForeignKey("library_files.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "parent_series_id",
            sa.Integer(),
            sa.ForeignKey("series.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("suggested_comicvine_id", sa.Integer(), nullable=True),
        sa.Column("suggested_title", sa.String(500), nullable=True),
        sa.Column("suggested_year", sa.Integer(), nullable=True),
        sa.Column("suggested_publisher", sa.String(200), nullable=True),
        sa.Column("suggested_series_type", sa.String(50), server_default="standard"),
        sa.Column("detection_source", sa.String(50), server_default="filename"),
        sa.Column("confidence_score", sa.Float(), server_default="0.0"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("pending", "accepted", "dismissed", name="suggestionstatus"),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_matching_suggestions_status",
        "matching_suggestions",
        ["status"],
    )
    op.create_index(
        "ix_matching_suggestions_file",
        "matching_suggestions",
        ["library_file_id"],
    )


def downgrade() -> None:
    op.drop_table("matching_suggestions")
    op.drop_index("ix_series_parent_series_id", "series")
    with op.batch_alter_table("series", schema=None) as batch_op:
        batch_op.drop_column("parent_series_id")
    op.drop_index("ix_series_series_type", "series")
    op.drop_column("series", "series_type")
