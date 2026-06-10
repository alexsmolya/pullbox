"""encrypt existing plaintext secrets

Revision ID: a1b2c3d4e5f6
Revises: f1a5c3d89b47
Create Date: 2026-02-28 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "f1a5c3d89b47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Column length increased to hold Fernet tokens (~200+ chars for a 32-char key)
_NEW_LENGTH = 1024


def upgrade() -> None:
    """Encrypt plaintext secrets and widen columns for ciphertext.

    This migration:
    1. Widens api_key / password columns to hold Fernet tokens.
    2. Encrypts every non-empty plaintext value in-place.
    """
    from pullbox.core.encryption import encrypt_secret, is_encrypted

    # ── Widen columns (SQLite ignores length but other DBs need it) ──
    # SQLite ALTER COLUMN is a no-op for length, but we do it for
    # forward compatibility with PostgreSQL.
    with op.batch_alter_table("download_client_configs") as batch:
        batch.alter_column("api_key", type_=sa.String(_NEW_LENGTH))
        batch.alter_column("password", type_=sa.String(_NEW_LENGTH))

    with op.batch_alter_table("indexer_configs") as batch:
        batch.alter_column("api_key", type_=sa.String(_NEW_LENGTH))

    # ── Encrypt download client secrets ──────────────────────────────
    conn = op.get_bind()

    rows = conn.execute(
        sa.text("SELECT id, api_key, password FROM download_client_configs")
    ).fetchall()
    for row in rows:
        row_id, api_key, password = row[0], row[1], row[2]
        updates = {}
        if api_key and not is_encrypted(api_key):
            updates["api_key"] = encrypt_secret(api_key)
        if password and not is_encrypted(password):
            updates["password"] = encrypt_secret(password)
        if updates:
            set_clause = ", ".join(f"{k} = :val_{k}" for k in updates)
            params = {f"val_{k}": v for k, v in updates.items()}
            params["id"] = row_id
            conn.execute(
                sa.text(f"UPDATE download_client_configs SET {set_clause} WHERE id = :id"),
                params,
            )

    # ── Encrypt indexer secrets ──────────────────────────────────────
    rows = conn.execute(sa.text("SELECT id, api_key FROM indexer_configs")).fetchall()
    for row in rows:
        row_id, api_key = row[0], row[1]
        if api_key and not is_encrypted(api_key):
            conn.execute(
                sa.text("UPDATE indexer_configs SET api_key = :val WHERE id = :id"),
                {"val": encrypt_secret(api_key), "id": row_id},
            )

    # ── Encrypt Prowlarr API key in system_config ────────────────────
    rows = conn.execute(
        sa.text("SELECT key, value FROM system_config WHERE key = 'prowlarr_api_key'")
    ).fetchall()
    for row in rows:
        key, value = row[0], row[1]
        if value and not is_encrypted(value):
            conn.execute(
                sa.text("UPDATE system_config SET value = :val WHERE key = :key"),
                {"val": encrypt_secret(value), "key": key},
            )


def downgrade() -> None:
    """Decrypt secrets back to plaintext."""
    from pullbox.core.encryption import decrypt_secret, is_encrypted

    conn = op.get_bind()

    # Decrypt download client secrets
    rows = conn.execute(
        sa.text("SELECT id, api_key, password FROM download_client_configs")
    ).fetchall()
    for row in rows:
        row_id, api_key, password = row[0], row[1], row[2]
        updates = {}
        if api_key and is_encrypted(api_key):
            updates["api_key"] = decrypt_secret(api_key)
        if password and is_encrypted(password):
            updates["password"] = decrypt_secret(password)
        if updates:
            set_clause = ", ".join(f"{k} = :val_{k}" for k in updates)
            params = {f"val_{k}": v for k, v in updates.items()}
            params["id"] = row_id
            conn.execute(
                sa.text(f"UPDATE download_client_configs SET {set_clause} WHERE id = :id"),
                params,
            )

    # Decrypt indexer secrets
    rows = conn.execute(sa.text("SELECT id, api_key FROM indexer_configs")).fetchall()
    for row in rows:
        row_id, api_key = row[0], row[1]
        if api_key and is_encrypted(api_key):
            conn.execute(
                sa.text("UPDATE indexer_configs SET api_key = :val WHERE id = :id"),
                {"val": decrypt_secret(api_key), "id": row_id},
            )

    # Decrypt Prowlarr API key
    rows = conn.execute(
        sa.text("SELECT key, value FROM system_config WHERE key = 'prowlarr_api_key'")
    ).fetchall()
    for row in rows:
        key, value = row[0], row[1]
        if value and is_encrypted(value):
            conn.execute(
                sa.text("UPDATE system_config SET value = :val WHERE key = :key"),
                {"val": decrypt_secret(value), "key": key},
            )

    # Shrink columns back
    with op.batch_alter_table("download_client_configs") as batch:
        batch.alter_column("api_key", type_=sa.String(255))
        batch.alter_column("password", type_=sa.String(255))

    with op.batch_alter_table("indexer_configs") as batch:
        batch.alter_column("api_key", type_=sa.String(255))
