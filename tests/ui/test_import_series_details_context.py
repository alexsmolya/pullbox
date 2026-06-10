"""Tests for import review series details modal context loading."""

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
async def test_load_import_series_details_context_groups_pending_no_match_files(
    db_session,
) -> None:  # type: ignore[no-untyped-def]
    from pullbox.ui.import_series_details_context import load_import_series_details_context

    job = ImportJob(
        source_path="/tmp/comics",
        source_type=ImportSourceType.FILESYSTEM,
        status=ImportJobStatus.REVIEW,
    )
    db_session.add(job)
    await db_session.flush()

    imported_series = ImportedSeries(
        import_job_id=job.id,
        raw_series_name="Negation",
        file_count=1,
        has_files=True,
        sample_paths=[],
        status=ImportSeriesStatus.NO_MATCH,
    )
    db_session.add(imported_series)
    await db_session.flush()

    db_session.add(
        ImportedFile(
            import_job_id=job.id,
            import_series_id=imported_series.id,
            file_path="/tmp/comics/Negation 02 (CrossGen 2003).cbz",
            file_name="Negation 02 (CrossGen 2003).cbz",
            file_size=1024,
            file_format="cbz",
            status=ImportedFileStatus.PENDING,
        )
    )
    await db_session.flush()

    context = await load_import_series_details_context(
        db_session,
        job_id=job.id,
        series_id=imported_series.id,
    )

    assert context["job"].id == job.id
    assert context["imported_series"].id == imported_series.id
    assert context["duplicate_merge_actionable"] is False
    assert context["duplicate_scope_selected_count"] == 0
    assert context["duplicate_scope_importable_count"] == 0
    file_groups = context["file_groups"]
    assert len(file_groups) == 1
    assert file_groups[0]["key"] == "no_match"
    assert file_groups[0]["count"] == 1
    assert file_groups[0]["rows"][0]["filename_series_label"] == "Negation"
