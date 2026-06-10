"""Tests for Step 3 import reconciliation helper decisions."""

from __future__ import annotations

from pullbox.models.import_job import ImportedFile, ImportedFileStatus, ImportedSeries
from pullbox.models.issue import Issue, IssueType
from pullbox.schemas.import_job import ImportReconcileDecision
from pullbox.services.import_file_match_targets import (
    PROVIDER_MISSING_ISSUE_PLACEHOLDER_KIND,
    PROVIDER_MISSING_ISSUE_PLACEHOLDER_METHOD,
)


def _series() -> ImportedSeries:
    return ImportedSeries(
        id=11,
        import_job_id=4,
        raw_series_name="King Dracula",
        cv_title="King Dracula",
        cv_id=169964,
        user_selected_cv_id=169964,
        cv_issue_count=3,
    )


def _file(*, status: ImportedFileStatus = ImportedFileStatus.NO_MATCH) -> ImportedFile:
    return ImportedFile(
        id=22,
        import_job_id=4,
        import_series_id=11,
        file_path="/imports/King Dracula 04.cbz",
        file_name="King Dracula 04.cbz",
        status=status,
        parsed_issue_number=4.0,
        diagnostics={"existing": "kept"},
    )


def test_apply_reconcile_decisions_assigns_selected_issue() -> None:
    from pullbox.services.import_reconcile_helpers import apply_reconcile_decisions

    item = _series()
    imp_file = _file()
    issue = Issue(id=33, series_id=99, issue_number=4.0, comicvine_id=1116296)
    issue_options = [
        {
            "issue_cv_id": 1116296,
            "issue_number": 4.0,
            "title": "Final Sacrifice",
            "release_date": "2026-06-03",
            "cover_url": "https://example.test/cover.jpg",
            "issue_type": IssueType.ISSUE.value,
        }
    ]

    apply_reconcile_decisions(
        item=item,
        files=[imp_file],
        decisions=[
            ImportReconcileDecision(
                imported_file_id=22,
                action="assign",
                issue_cv_id=1116296,
            )
        ],
        issue_options=issue_options,
        local_issue_by_cv_id={1116296: issue},
        provisional_issue_number_for_file=lambda _item, _file, _options: None,
        provisional_issue_type_for_file=lambda _file: IssueType.ISSUE,
    )

    assert imp_file.status == ImportedFileStatus.MATCHED
    assert imp_file.matched_issue_id == 33
    assert imp_file.matched_issue_cv_id == 1116296
    assert imp_file.match_confidence == "manual"
    assert imp_file.match_method == "import_reconcile"
    assert imp_file.include_in_import is False
    assert imp_file.diagnostics["existing"] == "kept"
    assert imp_file.diagnostics["resolution"] == "assigned"
    assert imp_file.diagnostics["target_issue_summary"]["title"] == "Final Sacrifice"


def test_apply_reconcile_decisions_skips_unresolved_file() -> None:
    from pullbox.services.import_reconcile_helpers import apply_reconcile_decisions

    item = _series()
    imp_file = _file()

    apply_reconcile_decisions(
        item=item,
        files=[imp_file],
        decisions=[ImportReconcileDecision(imported_file_id=22, action="skip")],
        issue_options=[],
        local_issue_by_cv_id={},
        provisional_issue_number_for_file=lambda _item, _file, _options: None,
        provisional_issue_type_for_file=lambda _file: IssueType.ISSUE,
    )

    assert imp_file.status == ImportedFileStatus.SKIPPED
    assert imp_file.matched_issue_id is None
    assert imp_file.matched_issue_cv_id is None
    assert imp_file.match_method == "import_reconcile_skip"
    assert imp_file.include_in_import is False
    assert imp_file.diagnostics["resolution"] == "skipped"


def test_apply_reconcile_decisions_creates_provisional_target() -> None:
    from pullbox.services.import_reconcile_helpers import apply_reconcile_decisions

    item = _series()
    imp_file = _file(status=ImportedFileStatus.PENDING)

    apply_reconcile_decisions(
        item=item,
        files=[imp_file],
        decisions=[
            ImportReconcileDecision(
                imported_file_id=22,
                action="provisional",
                provisional_issue_number=4.0,
            )
        ],
        issue_options=[],
        local_issue_by_cv_id={},
        provisional_issue_number_for_file=lambda _item, _file, _options: 4.0,
        provisional_issue_type_for_file=lambda _file: IssueType.ISSUE,
    )

    assert imp_file.status == ImportedFileStatus.MATCHED
    assert imp_file.matched_issue_id is None
    assert imp_file.matched_issue_cv_id is None
    assert imp_file.match_confidence == "manual"
    assert imp_file.match_method == PROVIDER_MISSING_ISSUE_PLACEHOLDER_METHOD
    assert imp_file.include_in_import is False
    assert imp_file.diagnostics["existing"] == "kept"
    assert imp_file.diagnostics["kind"] == PROVIDER_MISSING_ISSUE_PLACEHOLDER_KIND
    assert imp_file.diagnostics["target_issue_number"] == 4.0
    assert imp_file.diagnostics["target_issue_type"] == IssueType.ISSUE.value
