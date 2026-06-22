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
from pullbox.models.series import IssueCatalogState, Series


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


@pytest.mark.asyncio
async def test_load_import_results_context_counts_pending_catalog_sync(db_session) -> None:  # type: ignore[no-untyped-def]
    from pullbox.ui.import_results_context import load_import_results_context

    job = ImportJob(
        source_path="/tmp/comics",
        source_type=ImportSourceType.FILESYSTEM,
        status=ImportJobStatus.COMPLETED,
    )
    db_session.add(job)
    await db_session.flush()

    hydrating = Series(
        title="Still Syncing",
        sort_title="Still Syncing",
        monitored=True,
        issue_catalog_state=IssueCatalogState.HYDRATING,
    )
    failed = Series(
        title="Needs Retry",
        sort_title="Needs Retry",
        monitored=True,
        issue_catalog_state=IssueCatalogState.FAILED,
        issue_catalog_error="ComicVine timed out",
    )
    complete = Series(
        title="Already Complete",
        sort_title="Already Complete",
        monitored=True,
        issue_catalog_state=IssueCatalogState.COMPLETE,
    )
    db_session.add_all([hydrating, failed, complete])
    await db_session.flush()

    db_session.add_all(
        [
            ImportedSeries(
                import_job_id=job.id,
                raw_series_name="Still Syncing",
                file_count=1,
                has_files=True,
                sample_paths=[],
                status=ImportSeriesStatus.IMPORTED,
                series_id=hydrating.id,
            ),
            ImportedSeries(
                import_job_id=job.id,
                raw_series_name="Needs Retry",
                file_count=1,
                has_files=True,
                sample_paths=[],
                status=ImportSeriesStatus.IMPORTED,
                series_id=failed.id,
            ),
            ImportedSeries(
                import_job_id=job.id,
                raw_series_name="Already Complete",
                file_count=1,
                has_files=True,
                sample_paths=[],
                status=ImportSeriesStatus.IMPORTED,
                series_id=complete.id,
            ),
        ]
    )
    await db_session.flush()

    context = await load_import_results_context(db_session, job)

    assert context["catalog_sync_pending_count"] == 1
    assert context["catalog_sync_failed_count"] == 1
    assert context["catalog_sync_attention_count"] == 2
    assert [item.title for item in context["catalog_sync_series"]] == [
        "Needs Retry",
        "Still Syncing",
    ]
