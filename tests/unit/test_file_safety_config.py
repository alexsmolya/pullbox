"""Unit tests for database-backed file safety settings."""

from __future__ import annotations

import pytest

from pullbox.core.file_safety import (
    DEFAULT_ALLOWED_EXTENSIONS,
    get_allowed_extensions,
    get_archive_size_limit_bytes,
    is_dangerous_file_blocking_enabled,
)
from pullbox.models.config import SystemConfig


@pytest.mark.asyncio
async def test_file_safety_settings_normalize_configured_values(db_session) -> None:  # type: ignore[no-untyped-def]
    db_session.add_all(
        [
            SystemConfig(
                key="allowed_import_extensions",
                value="CBZ, .PDF, epub, ,",
                value_type="string",
            ),
            SystemConfig(
                key="block_dangerous_files",
                value="false",
                value_type="bool",
            ),
            SystemConfig(
                key="archive_size_limit_mb",
                value="750",
                value_type="int",
            ),
        ]
    )
    await db_session.commit()

    assert await get_allowed_extensions(db_session) == {".cbz", ".pdf", ".epub"}
    assert await is_dangerous_file_blocking_enabled(db_session) is False
    assert await get_archive_size_limit_bytes(db_session) == 750 * 1024 * 1024


@pytest.mark.asyncio
async def test_file_safety_settings_fall_back_to_defaults_for_missing_or_invalid_values(
    db_session,
) -> None:  # type: ignore[no-untyped-def]
    db_session.add(
        SystemConfig(
            key="archive_size_limit_mb",
            value="not-a-number",
            value_type="int",
        )
    )
    await db_session.commit()

    assert await get_allowed_extensions(db_session) == set(DEFAULT_ALLOWED_EXTENSIONS)
    assert await is_dangerous_file_blocking_enabled(db_session) is True
    assert await get_archive_size_limit_bytes(db_session) == 2000 * 1024 * 1024
