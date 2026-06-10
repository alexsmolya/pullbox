"""Shared component-history loading for health overview routes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import ColumnElement, func, or_, select

from pullbox.models.health import HealthCheckResult as HealthCheckResultModel
from pullbox.ui.health_data import (
    _HEALTH_HISTORY_SORT_DEFAULT,
    _health_history_order_by,
    _health_history_prefers_subchecks,
    _normalize_health_history_sort,
)
from pullbox.ui.health_history_rows import build_health_history_rows

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

    from pullbox.ui.health_presenters import HealthHistoryRowView


@dataclass(frozen=True)
class HealthComponentHistoryBundle:
    """History rows and paging metadata keyed by health component."""

    history_by_component: dict[str, tuple[HealthHistoryRowView, ...]]
    page_by_component: dict[str, int]
    total_pages_by_component: dict[str, int]
    total_count_by_component: dict[str, int]
    sort_by_component: dict[str, str]
    search_by_component: dict[str, str]


async def load_health_component_histories(
    session: AsyncSession,
    *,
    component_keys: tuple[str, ...],
    detail_component_key: str | None,
    detail_history_page: int,
    detail_history_per_page: int,
    detail_history_sort: str,
    detail_history_search: str,
    current_time: datetime,
    relative_time_label: Callable[[datetime, datetime], str],
) -> HealthComponentHistoryBundle:
    """Load summary/detail history rows for the health overview presenter."""
    history_by_component: dict[str, tuple[HealthHistoryRowView, ...]] = {}
    page_by_component: dict[str, int] = {}
    total_pages_by_component: dict[str, int] = {}
    total_count_by_component: dict[str, int] = {}
    sort_by_component: dict[str, str] = {}
    search_by_component: dict[str, str] = {}

    detail_history_uses_subchecks = False
    if detail_component_key:
        detail_history_uses_subchecks = await _health_history_prefers_subchecks(
            session, detail_component_key
        )

    for component_key in component_keys:
        if component_key == detail_component_key:
            (
                rows,
                page,
                total_pages,
                total_count,
                normalized_sort,
                normalized_search,
            ) = await _load_detail_component_history(
                session,
                component_key=component_key,
                history_uses_subchecks=detail_history_uses_subchecks,
                page=detail_history_page,
                per_page=detail_history_per_page,
                sort=detail_history_sort,
                search=detail_history_search,
            )
        else:
            (
                rows,
                page,
                total_pages,
                total_count,
                normalized_sort,
                normalized_search,
            ) = await _load_summary_component_history(session, component_key=component_key)

        history_by_component[component_key] = build_health_history_rows(
            rows,
            key_prefix=component_key,
            current_time=current_time,
            relative_time_label=relative_time_label,
        )
        page_by_component[component_key] = page
        total_pages_by_component[component_key] = total_pages
        total_count_by_component[component_key] = total_count
        sort_by_component[component_key] = normalized_sort
        search_by_component[component_key] = normalized_search

    return HealthComponentHistoryBundle(
        history_by_component=history_by_component,
        page_by_component=page_by_component,
        total_pages_by_component=total_pages_by_component,
        total_count_by_component=total_count_by_component,
        sort_by_component=sort_by_component,
        search_by_component=search_by_component,
    )


async def _load_detail_component_history(
    session: AsyncSession,
    *,
    component_key: str,
    history_uses_subchecks: bool,
    page: int,
    per_page: int,
    sort: str,
    search: str,
) -> tuple[tuple[HealthCheckResultModel, ...], int, int, int, str, str]:
    normalized_search = search.strip()
    normalized_sort = _normalize_health_history_sort(sort)
    page_size = max(1, per_page)
    filters: list[ColumnElement[bool]] = [
        HealthCheckResultModel.component == component_key,
        HealthCheckResultModel.is_summary.is_(not history_uses_subchecks),
        HealthCheckResultModel.subject_key.is_(None),
    ]
    if normalized_search:
        from pullbox.core.db_utils import escape_like

        search_term = f"%{escape_like(normalized_search)}%"
        filters.append(
            or_(
                HealthCheckResultModel.check_name.ilike(search_term),
                HealthCheckResultModel.message.ilike(search_term),
            )
        )
    total_count = int(
        (
            await session.execute(select(func.count(HealthCheckResultModel.id)).where(*filters))
        ).scalar_one()
        or 0
    )
    total_pages = max(1, (total_count + page_size - 1) // page_size)
    normalized_page = min(max(1, page), total_pages)
    rows = (
        (
            await session.execute(
                select(HealthCheckResultModel)
                .where(*filters)
                .order_by(*_health_history_order_by(normalized_sort))
                .offset((normalized_page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return (
        tuple(rows),
        normalized_page,
        total_pages,
        total_count,
        normalized_sort,
        normalized_search,
    )


async def _load_summary_component_history(
    session: AsyncSession,
    *,
    component_key: str,
) -> tuple[tuple[HealthCheckResultModel, ...], int, int, int, str, str]:
    rows = (
        (
            await session.execute(
                select(HealthCheckResultModel)
                .where(HealthCheckResultModel.component == component_key)
                .where(HealthCheckResultModel.is_summary.is_(True))
                .where(HealthCheckResultModel.subject_key.is_(None))
                .order_by(HealthCheckResultModel.checked_at.desc())
                .limit(10)
            )
        )
        .scalars()
        .all()
    )
    return (
        tuple(rows),
        1,
        1,
        len(rows),
        _HEALTH_HISTORY_SORT_DEFAULT,
        "",
    )
