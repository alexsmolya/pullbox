"""Loader helpers for health UI routes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncSession

    from pullbox.services.search_service import SearchStats


@dataclass(frozen=True)
class HealthOverviewLoadResult:
    """Shared health overview state needed by dashboard and registry routes."""

    overall_status: str
    health_view: Any


async def load_health_overview(
    session: AsyncSession,
    *,
    load_health_data: Callable[[AsyncSession], Awaitable[tuple[list[object], str]]],
    get_search_stats: Callable[[AsyncSession], Awaitable[SearchStats]],
    build_health_view: Callable[..., Awaitable[Any]],
    **health_view_options: Any,
) -> HealthOverviewLoadResult:
    """Load raw health data and build the shared health presenter."""
    components, overall_status = await load_health_data(session)
    search_stats = await get_search_stats(session)
    health_view = await build_health_view(
        session,
        components=components,
        overall_status=overall_status,
        search_stats=search_stats,
        **health_view_options,
    )
    return HealthOverviewLoadResult(
        overall_status=overall_status,
        health_view=health_view,
    )
