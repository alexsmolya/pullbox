"""Download post-processing source cleanup helper tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

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


def test_cleanup_source_dir_removes_empty_download_folder(tmp_path: Path) -> None:
    """Empty per-download source folders should be removed best-effort."""
    from pullbox.tasks.download_post_processing_cleanup import cleanup_source_dir

    source_file = tmp_path / "downloads" / "complete" / "pullbox" / "job" / "Issue.cbz"
    source_file.parent.mkdir(parents=True)

    cleanup_source_dir(source_file)

    assert not source_file.parent.exists()


def test_cleanup_source_dir_keeps_folder_with_real_files(tmp_path: Path) -> None:
    """Folders containing non-junk files should not be removed."""
    from pullbox.tasks.download_post_processing_cleanup import cleanup_source_dir

    source_file = tmp_path / "downloads" / "complete" / "pullbox" / "job" / "Issue.cbz"
    source_file.parent.mkdir(parents=True)
    (source_file.parent / "extra.cbz").write_bytes(b"x" * 2048)

    cleanup_source_dir(source_file)

    assert source_file.parent.exists()
