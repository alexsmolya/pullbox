"""Utility-job log API helper functions."""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

from fastapi.responses import Response
from sqlalchemy import func as sa_func
from sqlalchemy import or_, select

from pullbox.core.exceptions import NotFoundError
from pullbox.utilities.models import UtilityJob, UtilityJobLog
from pullbox.utilities.schemas import (
    JobLogListResponse,
    JobLogResponse,
    JobResponse,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from pullbox.api.deps import DbSession


async def build_job_logs_response(
    *,
    session: DbSession,
    job_id: str,
    level: str | None,
    search: str | None,
    limit: int,
    offset: int,
) -> JobLogListResponse:
    """Return log entries for a utility job with optional level/search filtering."""
    job = await session.get(UtilityJob, job_id)
    if not job:
        raise NotFoundError("UtilityJob", job_id)

    filters = job_log_filters(job_id, level=level, search=search)

    count_query = select(sa_func.count(UtilityJobLog.id)).where(*filters)
    total_count = (await session.execute(count_query)).scalar_one()

    query = (
        select(UtilityJobLog).where(*filters).order_by(UtilityJobLog.id).limit(limit).offset(offset)
    )
    result = await session.execute(query)
    logs = list(result.scalars().all())

    return JobLogListResponse(
        entries=[job_log_to_response(log, job) for log in logs],
        total_count=total_count,
    )


async def build_job_logs_download_response(
    *,
    session: DbSession,
    job_id: str,
    level: str | None,
    search: str | None,
    job_to_response: Callable[[UtilityJob], JobResponse],
) -> Response:
    """Download filtered job log entries as a JSON attachment."""
    job = await session.get(UtilityJob, job_id)
    if not job:
        raise NotFoundError("UtilityJob", job_id)

    filters = job_log_filters(job_id, level=level, search=search)
    query = select(UtilityJobLog).where(*filters).order_by(UtilityJobLog.id)
    result = await session.execute(query)
    logs = list(result.scalars().all())
    payload = {
        "job": job_to_response(job).model_dump(mode="json"),
        "filters": {
            "level": level,
            "search": search,
        },
        "total_count": len(logs),
        "entries": [job_log_to_response(log, job).model_dump(mode="json") for log in logs],
    }

    ts_str = attachment_timestamp(job.created_at)
    filename = f"utility_job_{ts_str}.json"
    return Response(
        content=json.dumps(payload, indent=2) + "\n",
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def job_log_filters(
    job_id: str,
    *,
    level: str | None = None,
    search: str | None = None,
) -> list[Any]:
    """Build shared filters for utility job log queries."""
    filters = [UtilityJobLog.job_id == job_id]
    if level:
        filters.append(UtilityJobLog.level == level.upper())
    if search:
        pattern = f"%{search}%"
        filters.append(
            or_(
                UtilityJobLog.message.ilike(pattern),
                UtilityJobLog.file_path.ilike(pattern),
                UtilityJobLog.extra.ilike(pattern),
            )
        )
    return filters


def job_log_to_response(log: UtilityJobLog, job: UtilityJob) -> JobLogResponse:
    """Return a UI/download log row with useful utility diagnostic context."""
    response = JobLogResponse.model_validate(log)
    response.extra = build_job_log_extra(log, job)
    return response


def build_job_log_extra(log: UtilityJobLog, job: UtilityJob) -> dict[str, Any]:
    """Build the expanded JSON shown in utility job log details."""
    return {
        "job": {
            "id": job.id,
            "type": job.job_type,
            "display_name": job.display_name,
            "state": job.state,
            "progress_pct": job.progress_pct,
            "total_items": job.total_items,
            "completed_items": job.completed_items,
            "failed_items": job.failed_items,
            "skipped_items": job.skipped_items,
            "warning_count": job.warning_count,
        },
        "entry": {
            "id": log.id,
            "item_id": log.item_id,
            "timestamp": log.timestamp,
            "level": log.level,
            "message": log.message,
            "file_path": log.file_path,
        },
        "details": parse_job_log_extra(log.extra),
    }


def parse_job_log_extra(raw_extra: str | None) -> dict[str, Any]:
    """Return stored executor detail as a stable mapping for log viewers."""
    if not raw_extra or raw_extra == "{}":
        return {}
    try:
        parsed = json.loads(raw_extra)
    except json.JSONDecodeError:
        return {"raw": raw_extra}
    if isinstance(parsed, dict):
        return parsed
    return {"value": parsed}


def attachment_timestamp(raw_value: str | None) -> str:
    """Return a filesystem-safe timestamp token for downloads."""
    if not raw_value:
        return "unknown"

    text = str(raw_value).strip()
    if not text:
        return "unknown"

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.strftime("%Y%m%d_%H%M%S")
    except ValueError:
        pass

    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 14:
        return f"{digits[:8]}_{digits[8:14]}"
    if digits:
        return digits[:32]

    sanitized = "".join(ch if ch.isalnum() else "_" for ch in text).strip("_")
    return sanitized[:32] or "unknown"
