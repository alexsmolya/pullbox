"""Download post-processing source helper characterization tests."""

from __future__ import annotations

from pathlib import Path


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
    assert callable(download_post_processing_sources._resolve_local_path)


def test_post_processing_integrity_exception_distinguishes_missing_source() -> None:
    """Transient missing files should stay typed separately from bad releases."""
    from pullbox.tasks import download_post_processing_sources

    exc = download_post_processing_sources._build_post_processing_integrity_exception(
        Path("/downloads/Missing.cbz"),
        ["File not found: /downloads/Missing.cbz"],
    )

    assert isinstance(exc, FileNotFoundError)
