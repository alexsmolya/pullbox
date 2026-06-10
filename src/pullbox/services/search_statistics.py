"""Search-log backed statistics read models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlalchemy import func as sa_func
from sqlalchemy import select

from pullbox.models.search_log import SearchLog

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class SearchStats:
    """Search statistics backed by the search_logs table."""

    total_searches: int = 0
    total_results_parsed: int = 0
    total_matched: int = 0
    total_rejected: int = 0
    type_distribution: dict[str, int] = field(default_factory=dict)
    confidence_breakdown: dict[str, int] = field(default_factory=dict)
    last_search_at: str | None = None


async def get_search_stats(session: AsyncSession) -> SearchStats:
    """Query search_logs to build persistent search statistics."""
    row = (
        await session.execute(
            select(
                sa_func.count(SearchLog.id).label("total_searches"),
                sa_func.coalesce(sa_func.sum(SearchLog.results_found), 0).label(
                    "total_results_parsed"
                ),
                sa_func.coalesce(
                    sa_func.sum(SearchLog.results_grabbed + SearchLog.results_queued), 0
                ).label("total_matched"),
                sa_func.coalesce(sa_func.sum(SearchLog.results_rejected), 0).label(
                    "total_rejected"
                ),
                sa_func.max(SearchLog.created_at).label("last_search_at"),
            )
        )
    ).one()

    last_search_at = row.last_search_at.isoformat() if row.last_search_at else None

    conf_rows = (
        await session.execute(
            select(SearchLog.best_confidence, sa_func.count(SearchLog.id))
            .where(SearchLog.best_confidence.is_not(None))
            .group_by(SearchLog.best_confidence)
        )
    ).all()
    confidence_breakdown = {str(level): int(count) for level, count in conf_rows}

    recent = (
        (
            await session.execute(
                select(SearchLog.details)
                .where(SearchLog.details.is_not(None))
                .order_by(SearchLog.created_at.desc())
                .limit(200)
            )
        )
        .scalars()
        .all()
    )

    type_distribution: dict[str, int] = {}
    for details in recent:
        if isinstance(details, dict):
            type_counts = details.get("type_distribution")
            if isinstance(type_counts, dict):
                for type_name, count in type_counts.items():
                    if isinstance(count, int):
                        type_distribution[type_name] = type_distribution.get(type_name, 0) + count

    return SearchStats(
        total_searches=int(row.total_searches),
        total_results_parsed=int(row.total_results_parsed),
        total_matched=int(row.total_matched),
        total_rejected=int(row.total_rejected),
        type_distribution=type_distribution,
        confidence_breakdown=confidence_breakdown,
        last_search_at=last_search_at,
    )
