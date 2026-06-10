"""Diagnostic collectors for utility jobs and logs."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def collect_utility_jobs(session: AsyncSession) -> list[dict[str, object]]:
    """Return recent utility jobs with counters, status, and timestamps."""
    from sqlalchemy import select

    from pullbox.utilities.models import UtilityJob

    result = await session.execute(
        select(UtilityJob).order_by(UtilityJob.created_at.desc()).limit(50)
    )
    jobs = result.scalars().all()
    return [
        {
            "id": j.id,
            "job_type": str(j.job_type),
            "display_name": j.display_name,
            "state": str(j.state),
            "config": j.config,
            "total_items": j.total_items,
            "completed_items": j.completed_items,
            "failed_items": j.failed_items,
            "skipped_items": j.skipped_items,
            "warning_count": j.warning_count,
            "queue_position": j.queue_position,
            "created_at": j.created_at,
            "started_at": j.started_at,
            "completed_at": j.completed_at,
            "created_by": j.created_by,
            "error_message": j.error_message,
            "parent_job_id": j.parent_job_id,
        }
        for j in jobs
    ]


def parse_utility_log_extra(raw_extra: str | None) -> dict[str, object] | str:
    """Return parsed utility log extra data when possible."""
    if not raw_extra:
        return {}
    try:
        parsed = json.loads(raw_extra)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    return raw_extra


async def collect_utility_job_logs(
    session: AsyncSession,
    job_ids: list[str],
) -> list[dict[str, object]]:
    """Return structured logs for the provided utility job ids."""
    if not job_ids:
        return []

    from sqlalchemy import select

    from pullbox.utilities.models import UtilityJobLog

    result = await session.execute(
        select(UtilityJobLog)
        .where(UtilityJobLog.job_id.in_(job_ids))
        .order_by(UtilityJobLog.id.desc())
    )
    logs = result.scalars().all()
    return [
        {
            "id": log.id,
            "job_id": log.job_id,
            "item_id": log.item_id,
            "timestamp": log.timestamp,
            "level": log.level,
            "message": log.message,
            "file_path": log.file_path,
            "extra": parse_utility_log_extra(log.extra),
        }
        for log in logs
    ]
