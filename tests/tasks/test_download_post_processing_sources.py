"""Download post-processing source helper characterization tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


def test_post_processing_source_module_exposes_path_helpers() -> None:
    """Source discovery and path mapping helpers should live beside the task module."""
    from pullbox.tasks import download_post_processing_sources

    assert download_post_processing_sources._POST_PROCESSING_SOURCE_RETRY_DELAYS == (
        0.0,
        0.5,
        1.0,
        2.0,
        4.0,
    )
    assert callable(download_post_processing_sources._find_comic_file)
    assert callable(download_post_processing_sources._probe_post_processing_source)
    assert callable(download_post_processing_sources._resolve_local_download_root)
    assert callable(download_post_processing_sources._resolve_local_path)


@pytest.mark.asyncio
async def test_resolve_local_download_root_uses_enabled_client_directory() -> None:
    """The configured local directory should define the cleanup boundary."""
    from pullbox.models.download import DownloadClientType
    from pullbox.tasks.download_post_processing_sources import _resolve_local_download_root

    result = MagicMock()
    result.scalars.return_value.first.return_value = SimpleNamespace(download_dir="/downloads/")
    session = SimpleNamespace(execute=AsyncMock(return_value=result))
    download = SimpleNamespace(download_client=DownloadClientType.SABNZBD)

    root = await _resolve_local_download_root(session, download)

    assert root == Path("/downloads")


@pytest.mark.asyncio
async def test_resolve_local_download_root_requires_configured_directory() -> None:
    """Cleanup should fail closed when no local download root is configured."""
    from pullbox.models.download import DownloadClientType
    from pullbox.tasks.download_post_processing_sources import _resolve_local_download_root

    result = MagicMock()
    result.scalars.return_value.first.return_value = SimpleNamespace(download_dir=None)
    session = SimpleNamespace(execute=AsyncMock(return_value=result))
    download = SimpleNamespace(download_client=DownloadClientType.SABNZBD)

    root = await _resolve_local_download_root(session, download)

    assert root is None


def test_post_processing_integrity_exception_distinguishes_missing_source() -> None:
    """Transient missing files should stay typed separately from bad releases."""
    from pullbox.tasks import download_post_processing_sources

    exc = download_post_processing_sources._build_post_processing_integrity_exception(
        Path("/downloads/Missing.cbz"),
        ["File not found: /downloads/Missing.cbz"],
    )

    assert isinstance(exc, FileNotFoundError)
