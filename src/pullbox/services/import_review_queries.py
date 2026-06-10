"""Import review query helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import func as sa_func
from sqlalchemy import select as sa_select

from pullbox.core.exceptions import NotFoundError
from pullbox.models.import_job import (
    ImportedFile,
    ImportedFileStatus,
    ImportedSeries,
    ImportJob,
    ImportSeriesStatus,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def get_files_for_series(
    session: AsyncSession,
    job_id: int,
    series_id: int,
    *,
    status_filter: ImportedFileStatus | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[ImportedFile], int]:
    """Return paginated files for a series within a job."""
    job = await session.get(ImportJob, job_id)
    if job is None:
        raise NotFoundError("ImportJob", job_id)

    item = await session.get(ImportedSeries, series_id)
    if item is None or item.import_job_id != job_id:
        raise NotFoundError("ImportedSeries", series_id)

    filters = [
        ImportedFile.import_job_id == job_id,
        ImportedFile.import_series_id == series_id,
    ]
    if status_filter is not None:
        filters.append(ImportedFile.status == status_filter)

    count_q = sa_select(sa_func.count(ImportedFile.id)).where(*filters)
    total = (await session.execute(count_q)).scalar_one()

    offset = (page - 1) * page_size
    query = (
        sa_select(ImportedFile)
        .where(*filters)
        .order_by(ImportedFile.id.asc())
        .limit(page_size)
        .offset(offset)
    )
    result = await session.execute(query)
    return list(result.scalars().all()), total


async def get_conflict_groups(
    session: AsyncSession,
    job_id: int,
) -> list[dict[str, Any]]:
    """Return all file and series conflict groups for a job."""
    job = await session.get(ImportJob, job_id)
    if job is None:
        raise NotFoundError("ImportJob", job_id)

    query = (
        sa_select(ImportedFile)
        .where(
            ImportedFile.import_job_id == job_id,
            ImportedFile.status == ImportedFileStatus.CONFLICT,
            ImportedFile.conflict_group_id.is_not(None),
        )
        .order_by(ImportedFile.conflict_group_id.asc(), ImportedFile.id.asc())
    )
    result = await session.execute(query)
    conflict_files = list(result.scalars().all())

    groups: dict[int, list[ImportedFile]] = {}
    for imp_file in conflict_files:
        group_id = imp_file.conflict_group_id
        assert group_id is not None
        groups.setdefault(group_id, []).append(imp_file)

    file_groups = [
        {
            "kind": "file_conflict",
            "conflict_group_id": group_id,
            "matched_issue_id": files[0].matched_issue_id,
            "files": files,
        }
        for group_id, files in groups.items()
    ]

    series_result = await session.execute(
        sa_select(ImportedSeries)
        .where(
            ImportedSeries.import_job_id == job_id,
            ImportedSeries.status == ImportSeriesStatus.NO_MATCH,
        )
        .order_by(ImportedSeries.id.asc())
    )
    series_conflicts: list[dict[str, Any]] = []
    for imp_series in series_result.scalars().all():
        diagnostics = dict(imp_series.diagnostics or {})
        if diagnostics.get("kind") != "series_conflict":
            continue
        files_result = await session.execute(
            sa_select(ImportedFile)
            .where(ImportedFile.import_series_id == imp_series.id)
            .order_by(ImportedFile.id.asc())
        )
        series_conflicts.append(
            {
                "kind": "series_conflict",
                "conflict_group_id": f"series-{imp_series.id}",
                "series_id": imp_series.id,
                "matched_issue_id": None,
                "files": list(files_result.scalars().all()),
                "diagnostics": diagnostics,
            }
        )

    return sorted(
        [*series_conflicts, *file_groups],
        key=lambda group: (
            0 if group.get("kind") == "series_conflict" else 1,
            str(group.get("conflict_group_id")),
        ),
    )
