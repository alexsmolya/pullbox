"""Tests for import job review-action API helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from pullbox.core.exceptions import ValidationError
from pullbox.models.import_job import (
    ImportedFile,
    ImportedFileStatus,
    ImportedSeries,
    ImportSeriesStatus,
)
from pullbox.schemas.import_job import (
    ConflictResolveRequest,
    SeriesSelectionBulkUpdateRequest,
)


def _imported_series(status: ImportSeriesStatus = ImportSeriesStatus.MATCHED) -> ImportedSeries:
    return ImportedSeries(
        id=12,
        import_job_id=3,
        status=status,
        raw_series_name="King Dracula",
        raw_year=2026,
        raw_publisher=None,
        file_count=1,
        has_files=True,
        sample_paths=["/imports/King Dracula 004.cbz"],
        source_folder="/imports",
        cv_id=165083,
        cv_title="King Dracula",
        cv_year=2026,
        cv_publisher="Dynamite",
        cv_issue_count=3,
        cv_url="https://comicvine.gamespot.com/king-dracula/4050-165083/",
        cv_match_score=100.0,
        cv_match_method="user",
        user_selected_cv_id=165083,
        selected_for_import=False,
        files_total=1,
        files_matched=1,
        files_duplicate=0,
        files_already_owned=0,
        files_conflict=0,
        files_no_match=0,
        files_imported=0,
        files_failed=0,
        series_id=None,
        error_message=None,
        diagnostics={},
    )


def _imported_file() -> ImportedFile:
    return ImportedFile(
        id=7,
        import_job_id=3,
        import_series_id=12,
        file_path="/imports/King Dracula 004.cbz",
        file_name="King Dracula 004.cbz",
        file_size=1234,
        file_format="cbz",
        parsed_series="King Dracula",
        parsed_issue_number=4.0,
        parsed_year=2026,
        has_comicinfo=False,
        comicvine_issue_id=None,
        issue_number_raw="004",
        status=ImportedFileStatus.MATCHED,
        matched_issue_id=99,
        matched_issue_cv_id=None,
        match_confidence="high",
        match_method="issue_number",
        conflict_group_id=44,
        duplicate_group_id=None,
        duplicate_of_file_id=None,
        is_preferred=True,
        include_in_import=False,
        content_hash=None,
        library_file_id=None,
        error_message=None,
        diagnostics={},
        created_at=datetime.now(tz=UTC),
    )


async def test_bulk_series_selection_response_includes_refreshed_selection_state() -> None:
    from pullbox.api.v1.import_job_review_actions import bulk_update_series_selection_response

    service = AsyncMock()
    service.bulk_update_series_selection.return_value = 2
    service.get_review_selection_state.return_value = {
        "matched_series_importable": 4,
        "matched_series_selected": 2,
        "duplicate_series_importable": 0,
        "duplicate_series_selected": 0,
        "duplicate_files_importable": 0,
        "duplicate_files_selected": 0,
        "importable_item_count": 4,
        "selected_item_count": 2,
        "selected_series_ids": [12, 13],
        "selected_duplicate_series_ids": [],
        "duplicate_selected_file_counts": {},
    }
    body = SeriesSelectionBulkUpdateRequest(
        include_in_import=True,
        imported_series_ids=[12, 13],
    )
    session = object()

    response = await bulk_update_series_selection_response(service, session, 3, body)

    assert response.updated == 2
    assert response.include_in_import is True
    assert response.selection_state.selected_item_count == 2
    service.bulk_update_series_selection.assert_awaited_once_with(
        session,
        3,
        include_in_import=True,
        imported_series_ids=[12, 13],
    )


async def test_resolve_conflict_response_maps_non_review_validation_to_400() -> None:
    from pullbox.api.v1.import_job_review_actions import resolve_conflict_response

    service = AsyncMock()
    service.resolve_conflict.side_effect = ValidationError("chosen file is not in conflict group")

    with pytest.raises(HTTPException) as exc_info:
        await resolve_conflict_response(
            service,
            object(),
            3,
            44,
            ConflictResolveRequest(chosen_file_id=7),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "chosen file is not in conflict group"


async def test_allow_safety_blocked_file_once_response_marks_matched_row_for_rematch() -> None:
    from pullbox.api.v1.import_job_review_actions import allow_safety_blocked_file_once_response

    service = AsyncMock()
    service.allow_safety_blocked_file_once.return_value = _imported_series()

    result = await allow_safety_blocked_file_once_response(service, object(), 3, 7)

    assert result.rematch_series_id == 12
    assert result.payload.id == 12
    assert result.payload.status == ImportSeriesStatus.MATCHED


async def test_resolve_conflict_response_returns_file_conflict_group() -> None:
    from pullbox.api.v1.import_job_review_actions import resolve_conflict_response

    service = AsyncMock()
    service.resolve_conflict.return_value = [_imported_file()]

    response = await resolve_conflict_response(
        service,
        object(),
        3,
        44,
        ConflictResolveRequest(chosen_file_id=7),
    )

    assert response.conflict_group_id == 44
    assert response.matched_issue_id == 99
    assert response.files[0].id == 7
