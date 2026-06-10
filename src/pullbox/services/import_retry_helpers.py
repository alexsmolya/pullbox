"""Helpers for creating fresh retry import jobs from historical runs."""

from __future__ import annotations

from typing import Any

from pullbox.schemas.import_job import ImportJobCreate

_RETRY_RUNTIME_FIELDS = (
    "move_to_library",
    "transfer_method",
    "torrent_import_strategy",
    "effective_import_strategy",
    "effective_transfer_method",
    "source_preserved",
    "convert_to_preferred_format",
    "update_embedded_comicinfo_from_match",
    "search_on_add",
)


def build_retry_import_request(original: Any) -> ImportJobCreate:
    """Build the creation request for a fresh retry job."""
    return ImportJobCreate(
        source_path=original.source_path,
        file_paths=list(original.selected_file_paths or []) or None,
        source_type=original.source_type,
        target_library_root_id=original.target_library_root_id,
        monitored=original.monitored,
        mylar3_path_map=dict(original.mylar3_path_map or {}),
        cv_match_threshold=original.cv_match_threshold,
        min_files_per_series=original.min_files_per_series,
        file_formats=original.file_formats,
    )


def copy_retry_import_settings(original: Any, retry: Any) -> None:
    """Copy runtime import policy fields onto the fresh retry job."""
    for field_name in _RETRY_RUNTIME_FIELDS:
        setattr(retry, field_name, getattr(original, field_name))
    retry.ingest_policy_snapshot = dict(original.ingest_policy_snapshot or {})
