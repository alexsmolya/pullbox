"""Import review preview query helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func as sa_func
from sqlalchemy import select as sa_select

from pullbox.core.exceptions import NotFoundError
from pullbox.models.import_job import ImportedSeries, ImportJob, ImportSeriesStatus
from pullbox.schemas.import_job import ImportedSeriesRead, ImportJobRead, ImportPreviewResponse

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def get_preview(
    session: AsyncSession,
    job_id: int,
    status_filter: list[ImportSeriesStatus] | None = None,
    page: int = 1,
    page_size: int = 50,
) -> ImportPreviewResponse:
    """Return paginated imported-series review rows for a job."""
    job = await session.get(ImportJob, job_id)
    if job is None:
        raise NotFoundError("ImportJob", job_id)

    query = sa_select(ImportedSeries).where(ImportedSeries.import_job_id == job_id)
    count_query = (
        sa_select(sa_func.count())
        .select_from(ImportedSeries)
        .where(ImportedSeries.import_job_id == job_id)
    )

    if status_filter:
        query = query.where(ImportedSeries.status.in_(status_filter))
        count_query = count_query.where(ImportedSeries.status.in_(status_filter))

    total_result = await session.execute(count_query)
    total = total_result.scalar() or 0

    offset = (page - 1) * page_size
    result = await session.execute(query.offset(offset).limit(page_size))
    items = result.scalars().all()

    return ImportPreviewResponse(
        job=ImportJobRead.model_validate(job),
        items=[ImportedSeriesRead.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )
