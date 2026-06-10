"""add series path, library_root_id, and issue_type columns

Revision ID: g2b3d4e5f678
Revises: a1b2c3d4e5f6
Create Date: 2026-03-01 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "g2b3d4e5f678"
down_revision: str | Sequence[str] = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# New naming config keys to seed
_NEW_CONFIG_KEYS: list[tuple[str, str, str]] = [
    ("series_folder_template", "{Series} ({Year})", "string"),
    ("comic_file_template", "{Series} ({Year}) #{Issue:03d}", "string"),
    ("annual_file_template", "{Series} ({Year}) Annual #{Issue:03d}", "string"),
    ("non_standard_file_template", "{Series} ({Year}) {Type}", "string"),
    ("rename_on_import", "true", "bool"),
    ("replace_illegal_characters", "true", "bool"),
    ("colon_replacement", "dash", "string"),
    ("create_empty_series_folders", "false", "bool"),
    ("delete_empty_folders", "true", "bool"),
]


def upgrade() -> None:
    """Add series folder columns, issue_type, and seed naming config."""
    # --- Schema changes (use batch mode for SQLite compatibility) ---

    # 1. Add path and library_root_id to series
    with op.batch_alter_table("series") as batch_op:
        batch_op.add_column(sa.Column("path", sa.String(length=1000), nullable=True))
        batch_op.add_column(sa.Column("library_root_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_series_library_root_id",
            "library_roots",
            ["library_root_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # 2. Add issue_type to issues (default 'issue')
    with op.batch_alter_table("issues") as batch_op:
        batch_op.add_column(
            sa.Column(
                "issue_type",
                sa.String(length=20),
                nullable=False,
                server_default="issue",
            ),
        )

    # --- Data migration: rename naming_template → comic_file_template ---
    conn = op.get_bind()
    result = conn.execute(
        sa.text("SELECT value FROM system_config WHERE key = 'naming_template'")
    ).fetchone()
    if result:
        # Copy old value to new key (if new key doesn't exist yet)
        existing_new = conn.execute(
            sa.text("SELECT key FROM system_config WHERE key = 'comic_file_template'")
        ).fetchone()
        if not existing_new:
            conn.execute(
                sa.text(
                    "INSERT INTO system_config (key, value, value_type) "
                    "VALUES ('comic_file_template', :val, 'string')"
                ),
                {"val": result[0]},
            )
        # Remove old key
        conn.execute(sa.text("DELETE FROM system_config WHERE key = 'naming_template'"))

    # --- Seed new naming config keys (skip if already present) ---
    for key, default_val, val_type in _NEW_CONFIG_KEYS:
        existing = conn.execute(
            sa.text("SELECT key FROM system_config WHERE key = :k"),
            {"k": key},
        ).fetchone()
        if not existing:
            conn.execute(
                sa.text("INSERT INTO system_config (key, value, value_type) VALUES (:k, :v, :t)"),
                {"k": key, "v": default_val, "t": val_type},
            )


def downgrade() -> None:
    """Remove series folder columns, issue_type, and naming config keys."""
    # Remove config keys
    conn = op.get_bind()
    for key, _, _ in _NEW_CONFIG_KEYS:
        conn.execute(
            sa.text("DELETE FROM system_config WHERE key = :k"),
            {"k": key},
        )

    # Remove issue_type from issues
    #   SQLite requires batch mode for column drops
    with op.batch_alter_table("issues") as batch_op:
        batch_op.drop_column("issue_type")

    # Remove series folder columns
    with op.batch_alter_table("series") as batch_op:
        batch_op.drop_constraint("fk_series_library_root_id", type_="foreignkey")
        batch_op.drop_column("library_root_id")
        batch_op.drop_column("path")
