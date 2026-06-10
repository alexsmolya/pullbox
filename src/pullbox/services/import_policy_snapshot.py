"""Helpers for freezing import-time library policy on an import job."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pullbox.core.library_policy import (
    LibraryIngestPolicy,
    serialize_library_ingest_policy,
)

if TYPE_CHECKING:
    from pullbox.models.import_job import ImportJob


def apply_ingest_policy_to_import_job(
    job: ImportJob,
    policy: LibraryIngestPolicy,
) -> None:
    """Apply and snapshot the ingest policy that this import job should honor."""
    job.ingest_policy_snapshot = serialize_library_ingest_policy(policy)
    job.move_to_library = True
    job.transfer_method = policy.post_processing_method
    job.torrent_import_strategy = policy.torrent_import_strategy
    job.effective_import_strategy = "standard"
    job.effective_transfer_method = policy.post_processing_method
    job.source_preserved = policy.post_processing_method in {"copy", "hardlink", "symlink"}
    job.convert_to_preferred_format = policy.normalize_imported_archives_to_cbz
    job.update_embedded_comicinfo_from_match = policy.update_embedded_comicinfo_from_match
