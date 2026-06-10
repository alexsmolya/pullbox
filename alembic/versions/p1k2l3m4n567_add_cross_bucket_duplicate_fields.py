"""add cross-bucket duplicate import fields

Revision ID: p1k2l3m4n567
Revises: o0j1k2l3m456
Create Date: 2026-04-29 23:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "p1k2l3m4n567"
down_revision: str | Sequence[str] | None = "o0j1k2l3m456"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("import_jobs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "total_files_duplicate",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )

    with op.batch_alter_table("import_series") as batch_op:
        batch_op.add_column(
            sa.Column(
                "files_duplicate",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )

    with op.batch_alter_table("import_files") as batch_op:
        batch_op.add_column(sa.Column("duplicate_group_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("duplicate_of_file_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("content_hash", sa.String(length=64), nullable=True))
        batch_op.create_foreign_key(
            "fk_import_files_duplicate_of_file_id",
            "import_files",
            ["duplicate_of_file_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("import_files") as batch_op:
        batch_op.drop_constraint("fk_import_files_duplicate_of_file_id", type_="foreignkey")
        batch_op.drop_column("content_hash")
        batch_op.drop_column("duplicate_of_file_id")
        batch_op.drop_column("duplicate_group_id")

    with op.batch_alter_table("import_series") as batch_op:
        batch_op.drop_column("files_duplicate")

    with op.batch_alter_table("import_jobs") as batch_op:
        batch_op.drop_column("total_files_duplicate")
