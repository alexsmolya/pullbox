"""Tests for import file conflict helper contracts."""

from __future__ import annotations

from pullbox.models.import_job import ImportedFile, ImportedFileStatus
from pullbox.services.import_file_conflicts import (
    detect_conflicts,
    detect_cross_series_conflicts,
    preferred_conflict_reasons,
    rejected_conflict_reasons,
)
from pullbox.services.import_service import ImportService


def test_preferred_conflict_reasons_explain_metadata_confidence_and_size() -> None:
    preferred = ImportedFile(has_comicinfo=True, match_confidence="high", file_size=4096)
    smaller = ImportedFile(has_comicinfo=False, match_confidence="medium", file_size=1024)

    assert preferred_conflict_reasons(preferred, [smaller]) == [
        "ComicInfo metadata present",
        "Higher match confidence",
        "Largest file size",
    ]


def test_rejected_conflict_reasons_explain_losing_tiebreakers() -> None:
    preferred = ImportedFile(has_comicinfo=True, match_confidence="high", file_size=4096)
    candidate = ImportedFile(has_comicinfo=False, match_confidence="medium", file_size=1024)

    assert rejected_conflict_reasons(candidate, preferred) == [
        "No ComicInfo metadata",
        "Lower match confidence than the preferred file",
        "Smaller file than the preferred file",
    ]


def test_detect_conflicts_marks_group_and_details_preferred_file() -> None:
    preferred = ImportedFile(
        id=1,
        file_name="Batman 001.cbz",
        file_size=4096,
        file_format="cbz",
        has_comicinfo=True,
        match_confidence="high",
        matched_issue_id=100,
        status=ImportedFileStatus.MATCHED,
        include_in_import=True,
    )
    rejected = ImportedFile(
        id=2,
        file_name="Batman 001 variant.cbz",
        file_size=1024,
        file_format="cbz",
        has_comicinfo=False,
        match_confidence="medium",
        matched_issue_id=100,
        status=ImportedFileStatus.MATCHED,
        include_in_import=True,
    )

    conflict_count, group_counter, details = detect_conflicts([rejected, preferred], 7)

    assert conflict_count == 2
    assert group_counter == 8
    assert preferred.status == ImportedFileStatus.CONFLICT
    assert rejected.status == ImportedFileStatus.CONFLICT
    assert preferred.is_preferred is True
    assert rejected.is_preferred is False
    assert preferred.conflict_group_id == 8
    assert rejected.include_in_import is False
    assert rejected.diagnostics["why_not_selected"] == [
        "No ComicInfo metadata",
        "Lower match confidence than the preferred file",
        "Smaller file than the preferred file",
    ]
    assert preferred.diagnostics["scope"] == "series_row"
    assert preferred.diagnostics["previous_diagnostics"] == {}
    assert details[0]["preferred_file_id"] == preferred.id
    assert details[0]["preferred_file_name"] == preferred.file_name


def test_detect_conflicts_uses_fallback_issue_identities() -> None:
    cv_a = ImportedFile(
        id=1,
        file_name="Issue A.cbz",
        file_size=2048,
        matched_issue_cv_id=500,
        status=ImportedFileStatus.MATCHED,
    )
    cv_b = ImportedFile(
        id=2,
        file_name="Issue B.cbz",
        file_size=1024,
        matched_issue_cv_id=500,
        status=ImportedFileStatus.MATCHED,
    )
    parsed_a = ImportedFile(
        id=3,
        file_name="Parsed A.cbz",
        file_size=2048,
        parsed_issue_number=4.0,
        status=ImportedFileStatus.MATCHED,
    )
    parsed_b = ImportedFile(
        id=4,
        file_name="Parsed B.cbz",
        file_size=1024,
        parsed_issue_number=4.0,
        status=ImportedFileStatus.MATCHED,
    )

    conflict_count, group_counter, details = detect_conflicts(
        [cv_a, cv_b, parsed_a, parsed_b],
        0,
    )

    assert conflict_count == 4
    assert group_counter == 2
    assert len(details) == 2


def test_detect_cross_series_conflicts_only_groups_files_from_different_series_rows() -> None:
    first = ImportedFile(
        id=1,
        import_series_id=11,
        file_name="Agent Alpha 010.cbz",
        file_size=1024,
        has_comicinfo=False,
        match_confidence="medium",
        matched_issue_id=10,
        status=ImportedFileStatus.MATCHED,
        diagnostics={"target_state": "issue_match"},
    )
    second = ImportedFile(
        id=2,
        import_series_id=12,
        file_name="Agent Alpha 010 - Fucking Patriot.cbr",
        file_size=2048,
        has_comicinfo=False,
        match_confidence="medium",
        matched_issue_id=10,
        status=ImportedFileStatus.MATCHED,
        diagnostics={"target_state": "issue_match"},
    )
    same_series_row = ImportedFile(
        id=3,
        import_series_id=12,
        file_name="Agent Alpha 011.cbz",
        file_size=512,
        has_comicinfo=False,
        match_confidence="medium",
        matched_issue_id=10,
        status=ImportedFileStatus.MATCHED,
    )

    conflict_count, group_counter, details = detect_cross_series_conflicts(
        [first, second, same_series_row],
        4,
        target_series_key_by_file_id={
            1: ("cv", 144944),
            2: ("cv", 144944),
            3: ("cv", 144944),
        },
    )

    assert conflict_count == 3
    assert group_counter == 5
    assert len(details) == 1
    assert details[0]["scope"] == "cross_series"
    assert all(
        item.status == ImportedFileStatus.CONFLICT for item in [first, second, same_series_row]
    )
    assert first.diagnostics["scope"] == "cross_series"
    assert first.diagnostics["previous_diagnostics"] == {"target_state": "issue_match"}


def test_import_service_conflict_shims_remain_available() -> None:
    preferred = ImportedFile(has_comicinfo=False, match_confidence="medium", file_size=1024)

    assert ImportService._preferred_conflict_reasons(preferred, []) == [
        "Won the metadata tiebreaker"
    ]
