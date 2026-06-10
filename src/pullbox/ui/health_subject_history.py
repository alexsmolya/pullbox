"""Shared subject-history loading for health UI detail routes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import ColumnElement, func, or_, select

from pullbox.models.health import HealthCheckResult as HealthCheckResultModel
from pullbox.models.health import HealthStatus
from pullbox.ui.health_data import (
    _health_history_order_by,
    _health_history_prefers_subchecks,
    _normalize_health_history_sort,
)

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class HealthSubjectHistoryResult:
    """History rows and summary stats for one download client or indexer subject."""

    rows: tuple[HealthCheckResultModel, ...]
    page: int
    total_pages: int
    total_count: int
    normalized_sort: str
    normalized_search: str
    latest_healthy_at: datetime | None
    consecutive_failures: int


async def load_health_subject_history(
    session: AsyncSession,
    *,
    component_key: str,
    subject_key: str,
    page: int,
    sort: str,
    search: str,
    per_page: int = 10,
) -> HealthSubjectHistoryResult:
    """Load paginated health history plus summary-derived recovery stats."""
    normalized_search = search.strip()
    normalized_sort = _normalize_health_history_sort(sort)
    page_size = max(1, per_page)
    history_uses_subchecks = await _health_history_prefers_subchecks(
        session,
        component_key,
        subject_key=subject_key,
    )
    history_filters: list[ColumnElement[bool]] = [
        HealthCheckResultModel.component == component_key,
        HealthCheckResultModel.subject_key == subject_key,
        HealthCheckResultModel.is_summary.is_(not history_uses_subchecks),
    ]
    if normalized_search:
        from pullbox.core.db_utils import escape_like

        search_term = f"%{escape_like(normalized_search)}%"
        history_filters.append(
            or_(
                HealthCheckResultModel.check_name.ilike(search_term),
                HealthCheckResultModel.message.ilike(search_term),
            )
        )

    total_count = int(
        (
            await session.execute(
                select(func.count(HealthCheckResultModel.id)).where(*history_filters)
            )
        ).scalar_one()
        or 0
    )
    total_pages = max(1, (total_count + page_size - 1) // page_size)
    normalized_page = min(max(1, page), total_pages)
    rows = (
        (
            await session.execute(
                select(HealthCheckResultModel)
                .where(*history_filters)
                .order_by(*_health_history_order_by(normalized_sort))
                .offset((normalized_page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )

    latest_healthy_at = (
        await session.execute(
            select(HealthCheckResultModel.checked_at)
            .where(
                HealthCheckResultModel.component == component_key,
                HealthCheckResultModel.subject_key == subject_key,
                HealthCheckResultModel.is_summary.is_(True),
                HealthCheckResultModel.status == HealthStatus.HEALTHY,
            )
            .order_by(HealthCheckResultModel.checked_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    recent_summaries = (
        (
            await session.execute(
                select(HealthCheckResultModel.status)
                .where(
                    HealthCheckResultModel.component == component_key,
                    HealthCheckResultModel.subject_key == subject_key,
                    HealthCheckResultModel.is_summary.is_(True),
                )
                .order_by(HealthCheckResultModel.checked_at.desc())
                .limit(25)
            )
        )
        .scalars()
        .all()
    )
    consecutive_failures = 0
    for summary_status in recent_summaries:
        if summary_status == HealthStatus.HEALTHY:
            break
        consecutive_failures += 1

    return HealthSubjectHistoryResult(
        rows=tuple(rows),
        page=normalized_page,
        total_pages=total_pages,
        total_count=total_count,
        normalized_sort=normalized_sort,
        normalized_search=normalized_search,
        latest_healthy_at=latest_healthy_at,
        consecutive_failures=consecutive_failures,
    )
