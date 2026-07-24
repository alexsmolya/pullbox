"""Download post-processing source cleanup helper tests."""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import pytest

from pullbox.models.download import DownloadClientType

if TYPE_CHECKING:
    from pathlib import Path


def test_should_cleanup_source_dir_only_for_moved_usenet_downloads() -> None:
    """Only moved SABnzbd/NZBGet downloads should trigger source-folder cleanup."""
    from pullbox.tasks.download_post_processing_cleanup import should_cleanup_source_dir

    assert should_cleanup_source_dir("move", DownloadClientType.SABNZBD) is True
    assert should_cleanup_source_dir("move", DownloadClientType.NZBGET) is True
    assert should_cleanup_source_dir("copy", DownloadClientType.SABNZBD) is False
    assert should_cleanup_source_dir("move", DownloadClientType.QBITTORRENT) is False
    assert should_cleanup_source_dir("move", None) is False


def test_cleanup_source_dir_removes_empty_shallow_download_folder(tmp_path: Path) -> None:
    """A job directly beneath the configured root should be removable."""
    from pullbox.tasks.download_post_processing_cleanup import cleanup_source_dir

    download_root = tmp_path / "downloads"
    source_dir = download_root / "job"
    source_dir.mkdir(parents=True)

    result = cleanup_source_dir(source_dir, download_root)

    assert result.removed is True
    assert result.reason == "removed"
    assert not source_dir.exists()


def test_cleanup_source_dir_keeps_folder_with_real_files(tmp_path: Path) -> None:
    """Folders containing non-junk files should not be removed."""
    from pullbox.tasks.download_post_processing_cleanup import cleanup_source_dir

    download_root = tmp_path / "downloads"
    source_dir = download_root / "job"
    source_dir.mkdir(parents=True)
    (source_dir / "extra.cbz").write_bytes(b"x" * 2048)

    result = cleanup_source_dir(source_dir, download_root)

    assert result.removed is False
    assert result.reason == "content_remaining"
    assert source_dir.exists()


def test_cleanup_source_dir_removes_nested_empty_and_junk_content(tmp_path: Path) -> None:
    """Nested empty folders and harmless release metadata should not block cleanup."""
    from pullbox.tasks.download_post_processing_cleanup import cleanup_source_dir

    download_root = tmp_path / "downloads"
    source_dir = download_root / "job"
    (source_dir / "Sample").mkdir(parents=True)
    (source_dir / "release.nfo").write_text("metadata")

    result = cleanup_source_dir(source_dir, download_root)

    assert result.removed is True
    assert not source_dir.exists()


@pytest.mark.parametrize("target", ["root", "outside"])
def test_cleanup_source_dir_rejects_unsafe_target(tmp_path: Path, target: str) -> None:
    """Cleanup must never remove the configured root or a directory outside it."""
    from pullbox.tasks.download_post_processing_cleanup import cleanup_source_dir

    download_root = tmp_path / "downloads"
    download_root.mkdir()
    source_dir = download_root if target == "root" else tmp_path / "outside"
    source_dir.mkdir(exist_ok=True)

    result = cleanup_source_dir(source_dir, download_root)

    assert result.removed is False
    assert result.reason == "unsafe_path"
    assert source_dir.exists()


def test_cleanup_source_dir_reports_filesystem_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed deletion should be observable to the caller."""
    from pullbox.tasks.download_post_processing_cleanup import cleanup_source_dir

    download_root = tmp_path / "downloads"
    source_dir = download_root / "job"
    source_dir.mkdir(parents=True)

    def fail_remove(_path: str) -> None:
        raise PermissionError("denied")

    monkeypatch.setattr(shutil, "rmtree", fail_remove)

    result = cleanup_source_dir(source_dir, download_root)

    assert result.removed is False
    assert result.reason == "error"
    assert result.error == "denied"
    assert source_dir.exists()
