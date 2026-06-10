"""Helpers for provider series that have no matching issue targets."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pullbox.services.import_file_issue_signals import candidate_issue_number
from pullbox.services.import_file_match_candidates import reset_file_match_state

if TYPE_CHECKING:
    from pullbox.models.import_job import ImportedFile, ImportedSeries
    from pullbox.providers.base import MetadataProvider


def mark_files_missing_provider_targets(
    imp_series: ImportedSeries,
    files: list[ImportedFile],
) -> None:
    """Annotate files when a matched provider series has no matching issue target."""
    target_series_cv_id = imp_series.user_selected_cv_id or imp_series.cv_id
    for imp_file in files:
        existing_diagnostics = dict(imp_file.diagnostics or {})
        requested_issue_number = candidate_issue_number(imp_file)
        reset_file_match_state(imp_file)
        imp_file.matched_issue_id = None
        imp_file.matched_issue_cv_id = None
        imp_file.match_confidence = None
        imp_file.match_method = None
        imp_file.diagnostics = {
            **existing_diagnostics,
            "kind": "provider_issue_target_missing",
            "target_state": "no_provider_issue_target",
            "target_series_cv_id": target_series_cv_id,
            "target_series_title": imp_series.cv_title or imp_series.raw_series_name,
            "target_series_issue_count": imp_series.cv_issue_count,
            "requested_issue_cv_id": imp_file.comicvine_issue_id,
            "requested_issue_number": requested_issue_number,
            "rejection_reason": "Matched ComicVine series has no issue target for this file.",
        }


def can_mark_missing_issue_targets(
    imp_series: ImportedSeries,
    metadata_provider: MetadataProvider | None,
) -> bool:
    """Return True when an empty target index means issue targets were really absent."""
    if imp_series.series_id is not None:
        return True
    if imp_series.cv_id is None or metadata_provider is None:
        return False
    return callable(getattr(type(metadata_provider), "get_issues_for_series", None))
