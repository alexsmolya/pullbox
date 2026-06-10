"""Unit tests for import file split-series helpers."""

from __future__ import annotations

from pullbox.models.import_job import ImportedFile, ImportedFileStatus, ImportedSeries
from pullbox.services.import_file_split_series import move_file_to_split_series


def test_move_file_to_split_series_resets_match_state_and_updates_split_counts() -> None:
    parent_series = ImportedSeries(
        id=10,
        raw_series_name="Absolute Martian Manhunter",
        file_count=3,
    )
    split_series = ImportedSeries(
        id=20,
        raw_series_name="Absolute Martian Manhunter: Vol. 1: Martian Vision",
        sample_paths=[],
        file_count=0,
    )
    imp_file = ImportedFile(
        id=30,
        import_series_id=parent_series.id,
        file_path="/tmp/Absolute Martian Manhunter Vol 01.cbz",
        file_name="Absolute Martian Manhunter Vol 01.cbz",
        status=ImportedFileStatus.MATCHED,
        include_in_import=True,
        matched_issue_id=100,
        matched_issue_cv_id=200,
        match_confidence="high",
        match_method="comicvine_id",
        conflict_group_id=1,
        duplicate_group_id=2,
        duplicate_of_file_id=40,
        is_preferred=True,
        content_hash="abc123",
        diagnostics={"previous": "value"},
    )

    move_file_to_split_series(
        imp_file,
        split_series=split_series,
        parent_series=parent_series,
        trigger_issue_cv_id=111111,
        resolved_series_cv_id=168590,
    )

    assert imp_file.import_series_id == split_series.id
    assert imp_file.status == ImportedFileStatus.PENDING
    assert imp_file.include_in_import is False
    assert imp_file.matched_issue_id is None
    assert imp_file.matched_issue_cv_id is None
    assert imp_file.match_confidence is None
    assert imp_file.match_method is None
    assert imp_file.conflict_group_id is None
    assert imp_file.duplicate_group_id is None
    assert imp_file.duplicate_of_file_id is None
    assert imp_file.is_preferred is False
    assert imp_file.content_hash is None
    assert imp_file.diagnostics["previous"] == "value"
    assert imp_file.diagnostics["split_series"] == {
        "reason": "explicit_issue_series_mismatch",
        "source_import_series_id": parent_series.id,
        "source_import_series_name": parent_series.raw_series_name,
        "target_import_series_id": split_series.id,
        "target_series_cv_id": 168590,
        "trigger_issue_cv_id": 111111,
    }
    assert split_series.sample_paths == [imp_file.file_path]
    assert split_series.file_count == 1
