"""add health current status

Revision ID: d6e7f8g9h012
Revises: c5d6e7f8g901
Create Date: 2026-05-29
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "d6e7f8g9h012"
down_revision: str | Sequence[str] | None = "c5d6e7f8g901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "health_current_status",
        sa.Column("component", sa.String(length=100), nullable=False),
        sa.Column("current_key", sa.String(length=100), nullable=False),
        sa.Column("check_name", sa.String(length=100), nullable=False),
        sa.Column("subject_key", sa.String(length=100), nullable=True),
        sa.Column("subject_key_norm", sa.String(length=100), server_default="", nullable=False),
        sa.Column("subject_label", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=9), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("details_json", sa.Text(), nullable=True),
        sa.Column("response_time_ms", sa.Float(), nullable=True),
        sa.Column("run_id", sa.String(length=32), nullable=True),
        sa.Column("is_summary", sa.Boolean(), server_default="1", nullable=False),
        sa.Column(
            "checked_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "component",
            "subject_key_norm",
            "current_key",
            name="uq_health_current_status_identity",
        ),
    )
    op.create_index(
        "ix_health_current_component_summary",
        "health_current_status",
        ["component", "is_summary", "subject_key_norm"],
    )
    op.create_index(
        "ix_health_current_component_checked",
        "health_current_status",
        ["component", "checked_at"],
    )

    op.execute(
        """
        INSERT INTO health_current_status (
            component,
            current_key,
            check_name,
            subject_key,
            subject_key_norm,
            subject_label,
            status,
            message,
            details_json,
            response_time_ms,
            run_id,
            is_summary,
            checked_at
        )
        SELECT
            h.component,
            CASE WHEN h.is_summary THEN '__summary__' ELSE h.check_name END AS current_key,
            h.check_name,
            h.subject_key,
            COALESCE(h.subject_key, '') AS subject_key_norm,
            h.subject_label,
            h.status,
            h.message,
            h.details_json,
            h.response_time_ms,
            h.run_id,
            h.is_summary,
            h.checked_at
        FROM health_check_results h
        JOIN (
            SELECT
                component,
                COALESCE(subject_key, '') AS subject_key_norm,
                CASE WHEN is_summary THEN '__summary__' ELSE check_name END AS current_key,
                MAX(id) AS max_id
            FROM health_check_results
            GROUP BY
                component,
                COALESCE(subject_key, ''),
                CASE WHEN is_summary THEN '__summary__' ELSE check_name END
        ) latest ON h.id = latest.max_id
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_health_current_component_checked", table_name="health_current_status")
    op.drop_index("ix_health_current_component_summary", table_name="health_current_status")
    op.drop_table("health_current_status")
