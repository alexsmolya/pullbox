"""Import-job log query and download helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from fastapi.responses import PlainTextResponse
from sqlalchemy import func as sa_func
from sqlalchemy import select as sa_select

from pullbox.core.exceptions import NotFoundError
from pullbox.models.import_job import ImportJob, ImportJobLog
from pullbox.schemas.import_job import (
    ImportJobLogEntry,
    ImportJobLogsResponse,
)

if TYPE_CHECKING:
    from pullbox.api.deps import DbSession

_LOG_SEVERITY = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3}


def log_levels_at_or_above(level: str) -> list[str]:
    """Return log levels at or above the given severity."""
    threshold = _LOG_SEVERITY.get(level.upper(), 0)
    return [lvl for lvl, sev in _LOG_SEVERITY.items() if sev >= threshold]


async def build_import_job_logs_response(
    *,
    session: DbSession,
    job_id: int,
    page: int,
    page_size: int,
    level: str | None,
    after_id: int | None,
    order: Literal["asc", "desc"],
) -> ImportJobLogsResponse:
    """Return paginated log entries for an import job."""
    if after_id is not None and not isinstance(after_id, int):
        after_id = None

    job = await session.get(ImportJob, job_id)
    if job is None:
        raise NotFoundError("ImportJob", job_id)

    filters = [ImportJobLog.import_job_id == job_id]
    if level:
        filters.append(ImportJobLog.level.in_(log_levels_at_or_above(level)))
    if after_id is not None:
        filters.append(ImportJobLog.id > after_id)

    count_q = sa_select(sa_func.count(ImportJobLog.id)).where(*filters)
    total = (await session.execute(count_q)).scalar_one()

    offset = (page - 1) * page_size
    sort_order = ImportJobLog.logged_at.desc() if order == "desc" else ImportJobLog.logged_at.asc()
    query = (
        sa_select(ImportJobLog).where(*filters).order_by(sort_order).limit(page_size).offset(offset)
    )
    result = await session.execute(query)
    entries = result.scalars().all()

    return ImportJobLogsResponse(
        job_id=job_id,
        items=[ImportJobLogEntry.model_validate(e) for e in entries],
        total=total,
        page=page,
        page_size=page_size,
    )


async def build_import_job_logs_download_response(
    *,
    session: DbSession,
    job_id: int,
) -> PlainTextResponse:
    """Build a plain-text download response for all log entries on one import job."""
    job = await session.get(ImportJob, job_id)
    if job is None:
        raise NotFoundError("ImportJob", job_id)

    query = (
        sa_select(ImportJobLog)
        .where(ImportJobLog.import_job_id == job_id)
        .order_by(ImportJobLog.logged_at.asc())
    )
    result = await session.execute(query)
    entries = result.scalars().all()

    if not entries:
        content = f"# No log entries for import job {job_id}.\n"
    else:
        lines: list[str] = []
        for entry in entries:
            ts = entry.logged_at.isoformat() if entry.logged_at else "unknown"
            data_parts = " ".join(f"{k}={v}" for k, v in (entry.data or {}).items())
            extra = f"  {data_parts}" if data_parts else ""
            lines.append(f"{ts} [{entry.level:7}] {entry.event}{extra}")
        content = "\n".join(lines) + "\n"

    ts_str = job.created_at.strftime("%Y%m%d_%H%M%S") if job.created_at else "unknown"
    filename = f"import_job_{job_id}_{ts_str}.log"

    return PlainTextResponse(
        content=content,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
