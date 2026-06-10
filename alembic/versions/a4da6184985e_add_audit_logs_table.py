"""add audit_logs table

Revision ID: a4da6184985e
Revises: db06777618db
Create Date: 2026-03-02 17:43:17.026376

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a4da6184985e"
down_revision: str | Sequence[str] | None = "db06777618db"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "audit_logs",
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("source_ip", sa.String(length=45), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("username", sa.String(length=100), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_logs_event_type"), "audit_logs", ["event_type"], unique=False)
    op.create_index(
        "ix_audit_logs_event_type_timestamp",
        "audit_logs",
        ["event_type", "timestamp"],
        unique=False,
    )
    op.create_index("ix_audit_logs_timestamp_desc", "audit_logs", ["timestamp"], unique=False)
    op.create_index(
        "ix_audit_logs_user_id_timestamp", "audit_logs", ["user_id", "timestamp"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_audit_logs_user_id_timestamp", table_name="audit_logs")
    op.drop_index("ix_audit_logs_timestamp_desc", table_name="audit_logs")
    op.drop_index("ix_audit_logs_event_type_timestamp", table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_event_type"), table_name="audit_logs")
    op.drop_table("audit_logs")
