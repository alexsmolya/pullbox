"""Unit tests for import history context helpers."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from pullbox.models.import_job import (
    ImportedSeries,
    ImportJob,
    ImportJobStatus,
    ImportSeriesStatus,
    ImportSourceType,
)
from pullbox.ui.import_history import (
    _history_resume_step_for_job,
    _load_import_history_context,
    _normalize_import_history_sort,
)


def _job(
    *,
    status: ImportJobStatus,
    source_path: str = "/imports/source",
    import_started_at: datetime | None = None,
) -> ImportJob:
    return ImportJob(
        source_path=source_path,
        source_type=ImportSourceType.FILESYSTEM,
        status=status,
        import_started_at=import_started_at,
    )


def test_history_sort_normalization_keeps_known_fields_and_defaults_unknowns() -> None:
    assert _normalize_import_history_sort(None) == "-created_at"
    assert _normalize_import_history_sort("") == "-created_at"
    assert _normalize_import_history_sort("source_path") == "source_path"
    assert _normalize_import_history_sort("-status") == "-status"
    assert _normalize_import_history_sort("unsafe_field") == "-created_at"


@pytest.mark.parametrize(
    ("job", "expected_step"),
    [
        (_job(status=ImportJobStatus.REVIEW), 3),
        (_job(status=ImportJobStatus.PAUSED), 2),
        (
            _job(
                status=ImportJobStatus.PAUSED,
                import_started_at=datetime(2026, 6, 1, tzinfo=UTC),
            ),
            4,
        ),
        (_job(status=ImportJobStatus.MATCHING), 2),
        (_job(status=ImportJobStatus.IMPORTING), 4),
        (_job(status=ImportJobStatus.CANCELLING), 4),
        (_job(status=ImportJobStatus.COMPLETED), None),
    ],
)
def test_history_resume_steps_reflect_active_import_phase(
    job: ImportJob,
    expected_step: int | None,
) -> None:
    assert _history_resume_step_for_job(job) == expected_step


@pytest.mark.asyncio
async def test_import_history_context_sorts_paginates_and_restores_terminal_counts(
    db_session,
) -> None:  # type: ignore[no-untyped-def]
    terminal_job = ImportJob(
        source_path="/imports/page-00",
        source_type=ImportSourceType.FILESYSTEM,
        status=ImportJobStatus.COMPLETED,
        series_found=99,
        series_imported=99,
        series_failed=99,
        series_no_match=99,
    )
    db_session.add(terminal_job)
    await db_session.flush()
    db_session.add_all(
        [
            ImportedSeries(
                import_job_id=terminal_job.id,
                raw_series_name="Imported",
                status=ImportSeriesStatus.IMPORTED,
                file_count=1,
            ),
            ImportedSeries(
                import_job_id=terminal_job.id,
                raw_series_name="Failed",
                status=ImportSeriesStatus.FAILED,
                file_count=1,
            ),
            ImportedSeries(
                import_job_id=terminal_job.id,
                raw_series_name="No Match",
                status=ImportSeriesStatus.NO_MATCH,
                file_count=1,
            ),
        ]
    )
    for idx in range(1, 30):
        db_session.add(
            ImportJob(
                source_path=f"/imports/page-{idx:02d}",
                source_type=ImportSourceType.FILESYSTEM,
                status=ImportJobStatus.FAILED,
                series_found=idx,
                series_imported=idx,
                series_failed=0,
                series_no_match=0,
            )
        )
    await db_session.commit()

    context = await _load_import_history_context(
        db_session,
        sort="source_path",
        requested_page=2,
    )

    jobs = context["jobs"]
    assert len(jobs) == 5
    assert [job.source_path for job in jobs] == [  # type: ignore[attr-defined]
        "/imports/page-25",
        "/imports/page-26",
        "/imports/page-27",
        "/imports/page-28",
        "/imports/page-29",
    ]
    assert context["page"] == 2
    assert context["total_pages"] == 2
    assert context["clearable_jobs_total"] == 30

    first_page = await _load_import_history_context(
        db_session,
        sort="source_path",
        requested_page=1,
    )
    metrics = first_page["job_history_metrics"][terminal_job.id]  # type: ignore[index]
    assert metrics == {
        "series_found": 3,
        "series_imported": 1,
        "series_failed": 1,
        "series_no_match": 1,
    }


@pytest.mark.asyncio
async def test_import_history_context_filters_and_reports_live_summary(db_session) -> None:  # type: ignore[no-untyped-def]
    db_session.add_all(
        [
            ImportJob(
                source_path="/imports/needle-active",
                source_type=ImportSourceType.FILESYSTEM,
                status=ImportJobStatus.SCANNING,
            ),
            ImportJob(
                source_path="/imports/needle-paused",
                source_type=ImportSourceType.FILESYSTEM,
                status=ImportJobStatus.PAUSED,
            ),
            ImportJob(
                source_path="/imports/needle-completed",
                source_type=ImportSourceType.FILESYSTEM,
                status=ImportJobStatus.COMPLETED,
            ),
            ImportJob(
                source_path="/imports/other",
                source_type=ImportSourceType.FILESYSTEM,
                status=ImportJobStatus.FAILED,
            ),
        ]
    )
    await db_session.commit()

    context = await _load_import_history_context(
        db_session,
        search_query="needle",
        sort="-status",
        requested_page=10,
    )

    assert context["search_query"] == "needle"
    assert context["sort"] == "-status"
    assert context["page"] == 1
    assert context["total_jobs"] == 3
    assert context["history_has_live_jobs"] is True
    assert context["history_stats"] == {
        "active": 1,
        "resumable": 1,
        "results_ready": 1,
    }
    assert [job.source_path for job in context["jobs"]] == [  # type: ignore[index]
        "/imports/needle-paused",
        "/imports/needle-completed",
        "/imports/needle-active",
    ]
