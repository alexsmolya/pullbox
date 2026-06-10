"""ComicVine API key resolution — DB (encrypted) with env-var fallback.

Provides a single async function that all code paths should use to obtain
the active ComicVine API key.  The resolution order is:

1. ``comicvine_api_key`` stored (encrypted) in the ``system_config`` table.
2. The ``PULLBOX_COMICVINE_API_KEY`` environment variable (legacy).

An obfuscation helper is also provided for display in the settings UI.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select

from pullbox.core.encryption import decrypt_secret, encrypt_secret
from pullbox.models.config import SystemConfig

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


async def get_comicvine_api_key(session: AsyncSession) -> str:
    """Resolve the active ComicVine API key.

    Checks the database first (decrypting if needed), then falls back
    to the ``PULLBOX_COMICVINE_API_KEY`` environment variable.

    Returns:
        The plaintext API key, or an empty string if not configured.
    """
    result = await session.execute(
        select(SystemConfig.value).where(SystemConfig.key == "comicvine_api_key")
    )
    db_value = result.scalar_one_or_none()

    if db_value:
        try:
            plaintext = decrypt_secret(db_value)
            if plaintext:
                return plaintext
        except (ValueError, Exception):
            logger.warning("comicvine_api_key_decrypt_failed")

    # Fallback to environment variable
    from pullbox.config import get_settings

    env_key = get_settings().comicvine_api_key
    return env_key or ""


async def save_comicvine_api_key(session: AsyncSession, plaintext_key: str) -> None:
    """Encrypt and store the ComicVine API key in the database.

    Creates the config row if it doesn't exist, or updates it.
    """
    encrypted = encrypt_secret(plaintext_key) if plaintext_key else ""

    config = await session.get(SystemConfig, "comicvine_api_key")
    if config:
        config.value = encrypted
    else:
        config = SystemConfig(
            key="comicvine_api_key",
            value=encrypted,
            value_type="secret",
        )
        session.add(config)

    await session.flush()
    logger.info("comicvine_api_key_saved", encrypted=bool(plaintext_key))


def obfuscate_api_key(key: str) -> str:
    """Obfuscate an API key for display, showing only the last 5 characters.

    Returns:
        Something like ``"•••••••••••abcde"`` or ``""`` if empty.
    """
    if not key:
        return ""
    visible = min(5, len(key))
    return "•" * (len(key) - visible) + key[-visible:]
