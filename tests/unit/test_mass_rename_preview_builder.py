"""Tests for mass rename preview builder validation."""

from __future__ import annotations

import pytest

from pullbox.core.exceptions import ValidationError
from pullbox.utilities.preview_builders import build_mass_rename_preview
from pullbox.utilities.schemas import MassRenamePreviewRequest


@pytest.mark.asyncio
async def test_mass_rename_preview_rejects_invalid_target_before_db_work() -> None:
    with pytest.raises(ValidationError, match="target must be 'files' or 'folders'"):
        await build_mass_rename_preview(
            MassRenamePreviewRequest(target="covers", scope="library"),
            session=None,
        )


@pytest.mark.asyncio
async def test_mass_rename_preview_requires_manual_selection_before_db_work() -> None:
    with pytest.raises(ValidationError, match="Choose at least one file or folder"):
        await build_mass_rename_preview(
            MassRenamePreviewRequest(target="files", scope="manual", file_paths=[]),
            session=None,
        )
