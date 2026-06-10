"""Cover directory resolution — resolves covers base dir from comics_directory or settings."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pullbox.config import get_settings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def resolve_covers_dir(session: AsyncSession) -> Path:
    """Resolve the covers base directory.

    Priority:
    1. ``{comics_directory}/.covers/`` if comics_directory is configured
    2. ``settings.covers_dir`` (legacy/runtime fallback)
    """
    from sqlalchemy import select

    from pullbox.models.config import SystemConfig

    result = await session.execute(
        select(SystemConfig.value).where(SystemConfig.key == "comics_directory")
    )
    comics_dir = result.scalar_one_or_none()
    if comics_dir:
        return Path(comics_dir) / ".covers"

    return get_settings().covers_dir
