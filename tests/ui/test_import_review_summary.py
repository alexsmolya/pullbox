"""Tests for import review summary count loading."""

from __future__ import annotations

import pytest

from pullbox.models.import_job import (
    ImportedFile,
    ImportedFileStatus,
    ImportedSeries,
    ImportJob,
    ImportJobStatus,
    ImportSeriesStatus,
    ImportSourceType,
)


@pytest.mark.asyncio
async def test_load_import_review_summary_uses_persisted_review_rows(
    db_session,
) -> None:  # type: ignore[no-untyped-def]
    from pullbox.ui.import_review_summary import load_import_review_summary

    job = ImportJob(
        source_path="/tmp/import",
        source_type=ImportSourceType.FILESYSTEM,
        status=ImportJobStatus.REVIEW,
    )
    db_session.add(job)
    await db_session.flush()

    matched = ImportedSeries(
        import_job_id=job.id,
        raw_series_name="Negation",
        status=ImportSeriesStatus.MATCHED,
        file_count=1,
        files_matched=1,
        selected_for_import=True,
    )
    no_match = ImportedSeries(
        import_job_id=job.id,
        raw_series_name="Mystery Book",
        status=ImportSeriesStatus.NO_MATCH,
        file_count=1,
    )
    series_conflict = ImportedSeries(
        import_job_id=job.id,
        raw_series_name="Crossed Annual",
        status=ImportSeriesStatus.NO_MATCH,
        file_count=1,
        diagnostics={"kind": "series_conflict"},
    )
    duplicate = ImportedSeries(
        import_job_id=job.id,
        raw_series_name="In Library",
        status=ImportSeriesStatus.DUPLICATE,
        file_count=1,
        files_matched=1,
    )
    db_session.add_all([matched, no_match, series_conflict, duplicate])
    await db_session.flush()

    db_session.add_all(
        [
            ImportedFile(
                import_job_id=job.id,
                import_series_id=matched.id,
                file_path="/tmp/import/Negation 001.cbz",
                file_name="Negation 001.cbz",
                file_format="cbz",
                status=ImportedFileStatus.MATCHED,
            ),
            ImportedFile(
                import_job_id=job.id,
                import_series_id=no_match.id,
                file_path="/tmp/import/Mystery Book.cbz",
                file_name="Mystery Book.cbz",
                file_format="cbz",
                status=ImportedFileStatus.NO_MATCH,
            ),
            ImportedFile(
                import_job_id=job.id,
                import_series_id=series_conflict.id,
                file_path="/tmp/import/Crossed Annual.cbz",
                file_name="Crossed Annual.cbz",
                file_format="cbz",
                status=ImportedFileStatus.SAFETY_BLOCKED,
            ),
            ImportedFile(
                import_job_id=job.id,
                import_series_id=duplicate.id,
                file_path="/tmp/import/In Library 002.cbz",
                file_name="In Library 002.cbz",
                file_format="cbz",
                status=ImportedFileStatus.MATCHED,
            ),
        ]
    )
    await db_session.flush()

    summary = await load_import_review_summary(db_session, job)

    assert summary["series_total"] == 4
    assert summary["series_matched"] == 1
    assert summary["series_no_match"] == 1
    assert summary["series_candidate_conflicts"] == 1
    assert summary["series_conflicts_total"] == 1
    assert summary["files_total"] == 4
    assert summary["files_matched"] == 2
    assert summary["files_no_match"] == 1
    assert summary["files_safety_blocked"] == 1
    assert summary["matched_series_selected"] == 1
    assert summary["selected_items_total"] == 1
    assert summary["importable_items_total"] == 1
    assert summary["duplicate_files_importable"] == 1


@pytest.mark.asyncio
async def test_load_import_review_summary_blends_live_counters_for_active_scan(
    db_session,
) -> None:  # type: ignore[no-untyped-def]
    from pullbox.ui.import_review_summary import load_import_review_summary

    job = ImportJob(
        source_path="/tmp/import",
        source_type=ImportSourceType.FILESYSTEM,
        status=ImportJobStatus.MATCHING,
        scan_total_files=42,
        series_found=8,
        series_matched=5,
        series_no_match=2,
        total_files_imported=3,
        total_files_failed=1,
    )
    db_session.add(job)
    await db_session.flush()

    summary = await load_import_review_summary(db_session, job)

    assert summary["series_total"] == 8
    assert summary["series_matched"] == 5
    assert summary["series_no_match"] == 2
    assert summary["files_total"] == 42
    assert summary["files_imported"] == 3
    assert summary["files_failed"] == 1
