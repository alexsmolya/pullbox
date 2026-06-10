"""Tests for import Step 5 results context loading."""

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
async def test_load_import_results_context_splits_unmatched_queue_counts(db_session) -> None:  # type: ignore[no-untyped-def]
    from pullbox.ui.import_results_context import load_import_results_context

    job = ImportJob(
        source_path="/tmp/comics",
        source_type=ImportSourceType.FILESYSTEM,
        status=ImportJobStatus.COMPLETED,
        total_files_no_match=2,
        series_no_match=1,
    )
    db_session.add(job)
    await db_session.flush()

    imported_series = ImportedSeries(
        import_job_id=job.id,
        raw_series_name="Imported Series",
        file_count=1,
        has_files=True,
        sample_paths=[],
        status=ImportSeriesStatus.IMPORTED,
    )
    unmatched_series = ImportedSeries(
        import_job_id=job.id,
        raw_series_name="Unmatched Series",
        file_count=1,
        has_files=True,
        sample_paths=[],
        status=ImportSeriesStatus.NO_MATCH,
    )
    db_session.add_all([imported_series, unmatched_series])
    await db_session.flush()

    db_session.add_all(
        [
            ImportedFile(
                import_job_id=job.id,
                import_series_id=imported_series.id,
                file_path="/tmp/comics/imported-no-match.cbz",
                file_name="imported-no-match.cbz",
                file_size=1024,
                file_format="cbz",
                status=ImportedFileStatus.NO_MATCH,
            ),
            ImportedFile(
                import_job_id=job.id,
                import_series_id=unmatched_series.id,
                file_path="/tmp/comics/unmatched-series-file.cbz",
                file_name="unmatched-series-file.cbz",
                file_size=1024,
                file_format="cbz",
                status=ImportedFileStatus.NO_MATCH,
            ),
        ]
    )
    await db_session.flush()

    context = await load_import_results_context(db_session, job)

    assert context["files_no_match"] == 2
    assert context["orphaned_file_no_match_count"] == 1
    assert context["identified_series_file_no_match_count"] == 1
    assert context["no_match_count"] == 1
    assert context["unmatched_queue_count"] == 2
