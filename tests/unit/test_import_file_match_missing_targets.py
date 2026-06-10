"""Tests for missing provider issue-target helpers."""

from __future__ import annotations

from pullbox.models.import_job import ImportedFile, ImportedSeries
from pullbox.services.import_file_match_missing_targets import (
    can_mark_missing_issue_targets,
    mark_files_missing_provider_targets,
)


def test_mark_files_missing_provider_targets_resets_match_state_and_preserves_context() -> None:
    imp_series = ImportedSeries(
        raw_series_name="King Dracula",
        cv_id=169964,
        cv_title="King Dracula",
        cv_issue_count=3,
    )
    imp_file = ImportedFile(
        file_name="King Dracula 04 (of 04) (2026).cbr",
        parsed_issue_number=4.0,
        comicvine_issue_id=1116296,
        matched_issue_id=99,
        matched_issue_cv_id=1001,
        match_confidence="high",
        match_method="issue_number",
        diagnostics={"source_issue_type": "issue"},
    )

    mark_files_missing_provider_targets(imp_series, [imp_file])

    assert imp_file.matched_issue_id is None
    assert imp_file.matched_issue_cv_id is None
    assert imp_file.match_confidence is None
    assert imp_file.match_method is None
    assert imp_file.diagnostics == {
        "source_issue_type": "issue",
        "kind": "provider_issue_target_missing",
        "target_state": "no_provider_issue_target",
        "target_series_cv_id": 169964,
        "target_series_title": "King Dracula",
        "target_series_issue_count": 3,
        "requested_issue_cv_id": 1116296,
        "requested_issue_number": 4.0,
        "rejection_reason": "Matched ComicVine series has no issue target for this file.",
    }


def test_can_mark_missing_issue_targets_requires_trustworthy_absence() -> None:
    class ProviderWithFullIssueList:
        async def get_issues_for_series(self, _series_provider_id: str) -> list[object]:
            return []

    assert can_mark_missing_issue_targets(ImportedSeries(series_id=12), None) is True
    assert (
        can_mark_missing_issue_targets(
            ImportedSeries(cv_id=169964),
            ProviderWithFullIssueList(),
        )
        is True
    )
    assert can_mark_missing_issue_targets(ImportedSeries(cv_id=169964), None) is False
    assert can_mark_missing_issue_targets(ImportedSeries(), ProviderWithFullIssueList()) is False
