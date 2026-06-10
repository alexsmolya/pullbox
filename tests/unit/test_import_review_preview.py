"""Tests for import review preview helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pullbox.core.exceptions import NotFoundError
from pullbox.models.import_job import (
    ImportedSeries,
    ImportJob,
    ImportJobStatus,
    ImportSeriesStatus,
    ImportSourceType,
)
from pullbox.services.import_review_preview import get_preview

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def _create_job_row(session: AsyncSession) -> ImportJob:
    job = ImportJob(
        source_path="/tmp/comics",
        source_type=ImportSourceType.FILESYSTEM,
        status=ImportJobStatus.REVIEW,
    )
    session.add(job)
    await session.flush()
    return job


async def _create_series_row(
    session: AsyncSession,
    job: ImportJob,
    *,
    name: str,
    status: ImportSeriesStatus = ImportSeriesStatus.MATCHED,
) -> ImportedSeries:
    series = ImportedSeries(
        import_job_id=job.id,
        raw_series_name=name,
        raw_year=2024,
        status=status,
    )
    session.add(series)
    await session.flush()
    return series


async def test_get_preview_returns_paginated_rows(db_session: AsyncSession) -> None:
    job = await _create_job_row(db_session)
    for index in range(5):
        await _create_series_row(db_session, job, name=f"Series {index}")

    result = await get_preview(db_session, job.id, page=2, page_size=2)

    assert result.job.id == job.id
    assert result.total == 5
    assert result.page == 2
    assert result.page_size == 2
    assert [item.raw_series_name for item in result.items] == ["Series 2", "Series 3"]


async def test_get_preview_filters_by_status(db_session: AsyncSession) -> None:
    job = await _create_job_row(db_session)
    await _create_series_row(db_session, job, name="Matched", status=ImportSeriesStatus.MATCHED)
    await _create_series_row(db_session, job, name="Duplicate", status=ImportSeriesStatus.DUPLICATE)

    result = await get_preview(db_session, job.id, status_filter=[ImportSeriesStatus.DUPLICATE])

    assert result.total == 1
    assert result.items[0].raw_series_name == "Duplicate"


async def test_get_preview_raises_for_missing_job(db_session: AsyncSession) -> None:
    with pytest.raises(NotFoundError):
        await get_preview(db_session, 9999)
