"""Download post-processing source validation helper tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_resolve_and_validate_source_rejects_missing_client_path() -> None:
    """A completed download with no resolved path should fail before filesystem work."""
    from pullbox.tasks.download_post_processing_source_validation import (
        resolve_and_validate_source,
    )

    with pytest.raises(FileNotFoundError, match="did not report a file path"):
        await resolve_and_validate_source(
            session=object(),
            download=SimpleNamespace(id=7, downloaded_path=None),
            trace=SimpleNamespace(),
            runtime=SimpleNamespace(enter_phase=lambda phase: None),
            log=SimpleNamespace(debug=lambda *args, **kwargs: None),
            resolve_local_path=AsyncMock(return_value=None),
            probe_source=AsyncMock(),
            build_integrity_exception=lambda comic_file, errors: RuntimeError(errors),
        )
