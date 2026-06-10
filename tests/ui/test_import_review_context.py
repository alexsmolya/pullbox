"""Tests for import review table context loading."""

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
from pullbox.models.library import LibraryRoot


@pytest.mark.asyncio
async def test_load_import_review_context_filters_matched_rows_and_selection_state(
    db_session,
) -> None:  # type: ignore[no-untyped-def]
    from pullbox.ui.import_review_context import load_import_review_context

    root = LibraryRoot(name="Comics", path="/comics", enabled=True)
    job = ImportJob(
        source_path="/tmp/import",
        source_type=ImportSourceType.FILESYSTEM,
        status=ImportJobStatus.REVIEW,
    )
    db_session.add_all([root, job])
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
    db_session.add_all([matched, no_match])
    await db_session.flush()

    db_session.add(
        ImportedFile(
            import_job_id=job.id,
            import_series_id=matched.id,
            file_path="/tmp/import/Negation 001.cbz",
            file_name="Negation 001.cbz",
            file_format="cbz",
            status=ImportedFileStatus.MATCHED,
        )
    )
    await db_session.flush()

    context = await load_import_review_context(
        db_session,
        job,
        status="matched",
        page=1,
        sort=None,
    )

    assert context["job"].id == job.id
    assert context["current_view"] == "matched"
    assert context["status_filter"] == "matched"
    assert context["sort"] == "confidence"
    assert context["total"] == 1
    assert [item.id for item in context["series_items"]] == [matched.id]
    assert [root.id for root in context["library_roots"]] == [root.id]
    assert context["selected_series_ids"] == [matched.id]
    assert context["status_counts"]["matched"] == 1
    assert context["status_counts"]["no_match"] == 1
    assert context["review_summary"]["selected_items_total"] == 1
