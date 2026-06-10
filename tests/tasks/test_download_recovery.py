"""Download recovery module characterization tests."""

from __future__ import annotations

from datetime import timedelta


def test_recovery_module_exposes_retry_and_orphan_helpers() -> None:
    """Retry and orphan recovery should live in the adjacent recovery module."""
    from pullbox.tasks import download_recovery

    assert timedelta(minutes=10) == download_recovery._STALE_DOWNLOAD_TIMEOUT
    assert callable(download_recovery._process_retry_pending)
    assert callable(download_recovery._recover_orphaned_downloads)
