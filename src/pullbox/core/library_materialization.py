"""Library materialization planning for import and post-processing flows."""

from __future__ import annotations

from dataclasses import dataclass
from os import stat as os_stat
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from pullbox.models.download import DownloadClientType


@dataclass(frozen=True, slots=True)
class LibraryMaterializationPlan:
    """Resolved physical library artifact plan."""

    strategy: str
    source_preserved: bool
    materialization_method: str
    content_mutation_required: bool
    normalize_to_cbz: bool
    update_embedded_comicinfo: bool
    same_filesystem: bool
    reason: str


def paths_on_same_filesystem(source_path: Path, destination_path: Path) -> bool:
    """Return whether source and destination live on the same filesystem."""
    source_device = os_stat(source_path).st_dev
    destination_anchor = _nearest_existing_path(destination_path)
    return source_device == os_stat(destination_anchor).st_dev


def _nearest_existing_path(path: Path) -> Path:
    """Find the closest existing path to use for destination device checks."""
    current = path if path.exists() else path.parent
    while not current.exists() and current != current.parent:
        current = current.parent
    return current


def plan_library_materialization(
    *,
    download_client: DownloadClientType,
    torrent_import_strategy: str,
    preferred_transfer_method: str,
    same_filesystem: bool,
    normalize_to_cbz: bool,
    update_embedded_comicinfo: bool,
) -> LibraryMaterializationPlan:
    """Plan how a source artifact should become a library artifact."""
    content_mutation_required = normalize_to_cbz or update_embedded_comicinfo
    if download_client.is_torrent and torrent_import_strategy == "seed_safe":
        if content_mutation_required:
            return LibraryMaterializationPlan(
                strategy="seed_safe_torrent",
                source_preserved=True,
                materialization_method="copy",
                content_mutation_required=True,
                normalize_to_cbz=normalize_to_cbz,
                update_embedded_comicinfo=update_embedded_comicinfo,
                same_filesystem=same_filesystem,
                reason="seed_safe_content_mutation_copy_required",
            )
        if same_filesystem:
            return LibraryMaterializationPlan(
                strategy="seed_safe_torrent",
                source_preserved=True,
                materialization_method="hardlink",
                content_mutation_required=False,
                normalize_to_cbz=False,
                update_embedded_comicinfo=False,
                same_filesystem=True,
                reason="seed_safe_path_only_same_filesystem",
            )
        return LibraryMaterializationPlan(
            strategy="seed_safe_torrent",
            source_preserved=True,
            materialization_method="copy",
            content_mutation_required=False,
            normalize_to_cbz=False,
            update_embedded_comicinfo=False,
            same_filesystem=False,
            reason="seed_safe_path_only_cross_filesystem_copy_fallback",
        )

    return LibraryMaterializationPlan(
        strategy="standard",
        source_preserved=preferred_transfer_method in {"copy", "hardlink", "symlink"},
        materialization_method=preferred_transfer_method,
        content_mutation_required=content_mutation_required,
        normalize_to_cbz=normalize_to_cbz,
        update_embedded_comicinfo=update_embedded_comicinfo,
        same_filesystem=same_filesystem,
        reason="standard import strategy uses the configured transfer method",
    )
