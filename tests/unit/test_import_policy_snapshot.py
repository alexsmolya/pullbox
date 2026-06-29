"""Tests for import ingest policy snapshots."""

from __future__ import annotations

from pullbox.core.library_policy import (
    LibraryIngestPolicy,
    library_ingest_policy_from_snapshot,
    serialize_library_ingest_policy,
)
from pullbox.models.import_job import ImportJob, ImportSourceType
from pullbox.services.import_policy_snapshot import apply_ingest_policy_to_import_job


def _policy(**overrides: object) -> LibraryIngestPolicy:
    values = {
        "rename_on_import": True,
        "series_folder_template": "{Series} ({Year})",
        "comic_file_template": "{Series} ({Year}) #{Issue:03d}",
        "annual_file_template": "{Series} ({Year}) Annual #{Issue:03d}",
        "non_standard_file_template": "{Series} ({Year}) Vol {Volume:02d}",
        "single_non_standard_file_template": "{Series} ({Year}) {IssueType}",
        "replace_illegal_characters": True,
        "colon_replacement": "dash",
        "post_processing_method": "copy",
        "torrent_import_strategy": "standard",
        "normalize_imported_archives_to_cbz": True,
        "skip_existing_files": True,
        "update_embedded_comicinfo_from_match": True,
    }
    values.update(overrides)
    return LibraryIngestPolicy(**values)


def test_library_ingest_policy_snapshot_round_trips() -> None:
    policy = _policy(post_processing_method="move", skip_existing_files=False)

    restored = library_ingest_policy_from_snapshot(serialize_library_ingest_policy(policy))

    assert restored == policy


def test_apply_ingest_policy_to_import_job_updates_legacy_fields_and_snapshot() -> None:
    policy = _policy(post_processing_method="hardlink", normalize_imported_archives_to_cbz=False)
    job = ImportJob(source_path="/imports/test", source_type=ImportSourceType.FILESYSTEM)

    apply_ingest_policy_to_import_job(job, policy)

    assert job.ingest_policy_snapshot == serialize_library_ingest_policy(policy)
    assert job.transfer_method == "hardlink"
    assert job.effective_transfer_method == "copy"
    assert job.source_preserved is True
    assert job.convert_to_preferred_format is False
    assert job.update_embedded_comicinfo_from_match is True


def test_collection_import_move_policy_preserves_sources() -> None:
    policy = _policy(post_processing_method="move")
    job = ImportJob(source_path="/imports/drop", source_type=ImportSourceType.FILESYSTEM)

    apply_ingest_policy_to_import_job(job, policy)

    assert job.transfer_method == "move"
    assert job.effective_transfer_method == "copy"
    assert job.source_preserved is True
    assert job.ingest_policy_snapshot["post_processing_method"] == "move"


def test_mylar_collection_import_move_policy_preserves_sources() -> None:
    policy = _policy(post_processing_method="move")
    job = ImportJob(source_path="/imports/mylar.db", source_type=ImportSourceType.MYLAR3)

    apply_ingest_policy_to_import_job(job, policy)

    assert job.transfer_method == "move"
    assert job.effective_transfer_method == "copy"
    assert job.source_preserved is True


def test_incomplete_ingest_policy_snapshot_is_ignored() -> None:
    assert library_ingest_policy_from_snapshot({"post_processing_method": "copy"}) is None
