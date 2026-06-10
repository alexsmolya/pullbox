"""Tests for Step 3 import reconciliation orchestration helpers."""

from __future__ import annotations

import pytest

from pullbox.core.exceptions import ValidationError
from pullbox.models.import_job import (
    ImportedSeries,
    ImportJob,
    ImportJobStatus,
    ImportSeriesStatus,
    ImportSourceType,
)


@pytest.mark.asyncio
async def test_load_import_reconcile_item_requires_known_series_target(db_session) -> None:  # type: ignore[no-untyped-def]
    from pullbox.services.import_reconcile_service import load_import_reconcile_item

    job = ImportJob(
        source_path="/tmp/import",
        source_type=ImportSourceType.FILESYSTEM,
        status=ImportJobStatus.REVIEW,
    )
    db_session.add(job)
    await db_session.flush()

    item = ImportedSeries(
        import_job_id=job.id,
        raw_series_name="Mystery Book",
        status=ImportSeriesStatus.NO_MATCH,
        file_count=1,
    )
    db_session.add(item)
    await db_session.flush()

    with pytest.raises(ValidationError, match="Choose a ComicVine match"):
        await load_import_reconcile_item(db_session, job.id, item.id)


@pytest.mark.asyncio
async def test_load_import_reconcile_item_returns_review_job_and_series(db_session) -> None:  # type: ignore[no-untyped-def]
    from pullbox.services.import_reconcile_service import load_import_reconcile_item

    job = ImportJob(
        source_path="/tmp/import",
        source_type=ImportSourceType.FILESYSTEM,
        status=ImportJobStatus.REVIEW,
    )
    db_session.add(job)
    await db_session.flush()

    item = ImportedSeries(
        import_job_id=job.id,
        raw_series_name="Known Series",
        status=ImportSeriesStatus.NO_MATCH,
        file_count=1,
        cv_id=12345,
    )
    db_session.add(item)
    await db_session.flush()

    loaded_job, loaded_item = await load_import_reconcile_item(db_session, job.id, item.id)

    assert loaded_job.id == job.id
    assert loaded_item.id == item.id
