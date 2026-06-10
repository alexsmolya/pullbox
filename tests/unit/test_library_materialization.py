"""Tests for library materialization planning."""

from __future__ import annotations

from types import SimpleNamespace

from pullbox.core.library_materialization import (
    paths_on_same_filesystem,
    plan_library_materialization,
)
from pullbox.models.download import DownloadClientType


class TestSeedSafeTorrentMaterialization:
    """Seed-safe torrent import decision matrix."""

    def test_path_only_same_filesystem_hardlinks_and_preserves_source(self) -> None:
        plan = plan_library_materialization(
            download_client=DownloadClientType.QBITTORRENT,
            torrent_import_strategy="seed_safe",
            preferred_transfer_method="move",
            same_filesystem=True,
            normalize_to_cbz=False,
            update_embedded_comicinfo=False,
        )

        assert plan.strategy == "seed_safe_torrent"
        assert plan.source_preserved is True
        assert plan.materialization_method == "hardlink"
        assert plan.content_mutation_required is False
        assert plan.same_filesystem is True
        assert plan.reason == "seed_safe_path_only_same_filesystem"

    def test_path_only_cross_filesystem_copies_and_preserves_source(self) -> None:
        plan = plan_library_materialization(
            download_client=DownloadClientType.TRANSMISSION,
            torrent_import_strategy="seed_safe",
            preferred_transfer_method="hardlink",
            same_filesystem=False,
            normalize_to_cbz=False,
            update_embedded_comicinfo=False,
        )

        assert plan.strategy == "seed_safe_torrent"
        assert plan.source_preserved is True
        assert plan.materialization_method == "copy"
        assert plan.content_mutation_required is False
        assert plan.same_filesystem is False
        assert plan.reason == "seed_safe_path_only_cross_filesystem_copy_fallback"

    def test_normalize_to_cbz_copies_then_mutates_derived_artifact(self) -> None:
        plan = plan_library_materialization(
            download_client=DownloadClientType.DELUGE,
            torrent_import_strategy="seed_safe",
            preferred_transfer_method="hardlink",
            same_filesystem=True,
            normalize_to_cbz=True,
            update_embedded_comicinfo=False,
        )

        assert plan.strategy == "seed_safe_torrent"
        assert plan.source_preserved is True
        assert plan.materialization_method == "copy"
        assert plan.content_mutation_required is True
        assert plan.normalize_to_cbz is True
        assert plan.update_embedded_comicinfo is False
        assert plan.reason == "seed_safe_content_mutation_copy_required"

    def test_embedded_comicinfo_update_copies_then_mutates_derived_artifact(self) -> None:
        plan = plan_library_materialization(
            download_client=DownloadClientType.QBITTORRENT,
            torrent_import_strategy="seed_safe",
            preferred_transfer_method="hardlink",
            same_filesystem=True,
            normalize_to_cbz=False,
            update_embedded_comicinfo=True,
        )

        assert plan.strategy == "seed_safe_torrent"
        assert plan.source_preserved is True
        assert plan.materialization_method == "copy"
        assert plan.content_mutation_required is True
        assert plan.normalize_to_cbz is False
        assert plan.update_embedded_comicinfo is True
        assert plan.reason == "seed_safe_content_mutation_copy_required"

    def test_both_mutations_copy_once_and_preserve_source(self) -> None:
        plan = plan_library_materialization(
            download_client=DownloadClientType.QBITTORRENT,
            torrent_import_strategy="seed_safe",
            preferred_transfer_method="move",
            same_filesystem=False,
            normalize_to_cbz=True,
            update_embedded_comicinfo=True,
        )

        assert plan.strategy == "seed_safe_torrent"
        assert plan.source_preserved is True
        assert plan.materialization_method == "copy"
        assert plan.content_mutation_required is True
        assert plan.normalize_to_cbz is True
        assert plan.update_embedded_comicinfo is True
        assert plan.same_filesystem is False
        assert plan.reason == "seed_safe_content_mutation_copy_required"


class TestStandardMaterialization:
    """Existing behavior remains the default outside seed-safe torrent scope."""

    def test_standard_torrent_uses_preferred_transfer_method(self) -> None:
        plan = plan_library_materialization(
            download_client=DownloadClientType.QBITTORRENT,
            torrent_import_strategy="standard",
            preferred_transfer_method="move",
            same_filesystem=True,
            normalize_to_cbz=False,
            update_embedded_comicinfo=False,
        )

        assert plan.strategy == "standard"
        assert plan.source_preserved is False
        assert plan.materialization_method == "move"
        assert plan.content_mutation_required is False
        assert plan.reason == "standard import strategy uses the configured transfer method"

    def test_non_torrent_ignores_seed_safe_override_in_first_version(self) -> None:
        plan = plan_library_materialization(
            download_client=DownloadClientType.SABNZBD,
            torrent_import_strategy="seed_safe",
            preferred_transfer_method="move",
            same_filesystem=True,
            normalize_to_cbz=False,
            update_embedded_comicinfo=False,
        )

        assert plan.strategy == "standard"
        assert plan.source_preserved is False
        assert plan.materialization_method == "move"
        assert plan.content_mutation_required is False
        assert plan.reason == "standard import strategy uses the configured transfer method"

    def test_naming_only_settings_are_path_only_not_content_mutating(self) -> None:
        plan = plan_library_materialization(
            download_client=DownloadClientType.QBITTORRENT,
            torrent_import_strategy="seed_safe",
            preferred_transfer_method="copy",
            same_filesystem=True,
            normalize_to_cbz=False,
            update_embedded_comicinfo=False,
        )

        assert plan.content_mutation_required is False
        assert plan.materialization_method == "hardlink"


class TestFilesystemDetection:
    """Filesystem detection used by seed-safe torrent planning."""

    def test_existing_paths_on_same_temp_root_are_same_filesystem(self, tmp_path) -> None:
        source = tmp_path / "downloads" / "issue.cbz"
        destination = tmp_path / "library" / "issue.cbz"
        source.parent.mkdir()
        destination.parent.mkdir()
        source.write_bytes(b"comic")

        assert paths_on_same_filesystem(source, destination) is True

    def test_missing_destination_uses_nearest_existing_parent(self, tmp_path) -> None:
        source = tmp_path / "downloads" / "issue.cbz"
        destination = tmp_path / "library" / "Publisher" / "Series" / "issue.cbz"
        source.parent.mkdir()
        (tmp_path / "library").mkdir()
        source.write_bytes(b"comic")

        assert paths_on_same_filesystem(source, destination) is True

    def test_different_device_ids_are_cross_filesystem(self, tmp_path, monkeypatch) -> None:
        source = tmp_path / "downloads" / "issue.cbz"
        destination = tmp_path / "library" / "issue.cbz"
        source.parent.mkdir()
        destination.parent.mkdir()
        source.write_bytes(b"comic")

        def fake_stat(path):
            path_str = str(path)
            st_dev = 100 if "downloads" in path_str else 200
            return SimpleNamespace(st_dev=st_dev)

        monkeypatch.setattr("pullbox.core.library_materialization.os_stat", fake_stat)

        assert paths_on_same_filesystem(source, destination) is False
