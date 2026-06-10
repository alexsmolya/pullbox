"""Tests for import review query helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from pullbox.core.exceptions import NotFoundError
from pullbox.models.import_job import (
    ImportedFile,
    ImportedFileStatus,
    ImportedSeries,
    ImportJob,
    ImportJobStatus,
    ImportSeriesStatus,
    ImportSourceType,
)
from pullbox.services.import_review_queries import get_conflict_groups, get_files_for_series
from pullbox.services.import_service import ImportService

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
    name: str = "Absolute Wonder Woman",
    status: ImportSeriesStatus = ImportSeriesStatus.MATCHED,
    diagnostics: dict[str, object] | None = None,
) -> ImportedSeries:
    series = ImportedSeries(
        import_job_id=job.id,
        raw_series_name=name,
        status=status,
        file_count=0,
        diagnostics=diagnostics or {},
    )
    session.add(series)
    await session.flush()
    return series


def _make_file(
    job: ImportJob,
    series: ImportedSeries,
    *,
    name: str,
    status: ImportedFileStatus = ImportedFileStatus.MATCHED,
    conflict_group_id: int | None = None,
) -> ImportedFile:
    return ImportedFile(
        import_job_id=job.id,
        import_series_id=series.id,
        file_path=f"/tmp/comics/{name}",
        file_name=name,
        file_size=1024,
        file_format="cbz",
        status=status,
        conflict_group_id=conflict_group_id,
    )


async def test_get_files_for_series_filters_and_paginates(
    db_session: AsyncSession,
) -> None:
    job = await _create_job_row(db_session)
    series = await _create_series_row(db_session, job)
    db_session.add_all(
        [
            _make_file(job, series, name="issue-001.cbz", status=ImportedFileStatus.MATCHED),
            _make_file(job, series, name="issue-002.cbz", status=ImportedFileStatus.MATCHED),
            _make_file(job, series, name="issue-003.cbz", status=ImportedFileStatus.NO_MATCH),
        ]
    )
    await db_session.flush()

    files, total = await get_files_for_series(
        db_session,
        job.id,
        series.id,
        status_filter=ImportedFileStatus.MATCHED,
        page=2,
        page_size=1,
    )

    assert total == 2
    assert [file.file_name for file in files] == ["issue-002.cbz"]


async def test_get_files_for_series_requires_job_and_series(
    db_session: AsyncSession,
) -> None:
    job = await _create_job_row(db_session)

    with pytest.raises(NotFoundError):
        await get_files_for_series(db_session, job.id + 999, 1)

    with pytest.raises(NotFoundError):
        await get_files_for_series(db_session, job.id, 1)


async def test_get_conflict_groups_sorts_series_conflicts_before_file_conflicts(
    db_session: AsyncSession,
) -> None:
    job = await _create_job_row(db_session)
    file_series = await _create_series_row(db_session, job, name="File Conflict")
    series_conflict = await _create_series_row(
        db_session,
        job,
        name="Series Conflict",
        status=ImportSeriesStatus.NO_MATCH,
        diagnostics={"kind": "series_conflict", "reason": "ambiguous_match"},
    )
    db_session.add_all(
        [
            _make_file(
                job,
                file_series,
                name="variant-a.cbz",
                status=ImportedFileStatus.CONFLICT,
                conflict_group_id=7,
            ),
            _make_file(
                job,
                file_series,
                name="variant-b.cbz",
                status=ImportedFileStatus.CONFLICT,
                conflict_group_id=7,
            ),
            _make_file(job, series_conflict, name="series-conflict.cbz"),
        ]
    )
    await db_session.flush()

    groups = await get_conflict_groups(db_session, job.id)

    assert [group["kind"] for group in groups] == ["series_conflict", "file_conflict"]
    assert groups[0]["series_id"] == series_conflict.id
    assert groups[1]["conflict_group_id"] == 7
    assert [file.file_name for file in groups[1]["files"]] == [
        "variant-a.cbz",
        "variant-b.cbz",
    ]


async def test_import_service_review_query_shims_remain_available(
    db_session: AsyncSession,
) -> None:
    service = ImportService(
        series_service=AsyncMock(),
        metadata_service=AsyncMock(),
        event_bus=AsyncMock(),
    )
    job = await _create_job_row(db_session)
    series = await _create_series_row(db_session, job)

    files, total = await service.get_files_for_series(db_session, job.id, series.id)
    groups = await service.get_conflict_groups(db_session, job.id)

    assert files == []
    assert total == 0
    assert groups == []
