"""Health overview presenter assembly."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from typing import cast as typing_cast

from fastapi import HTTPException

from pullbox.core.duration_format import replace_duration_ms_tokens
from pullbox.ui.health_check_items import build_health_checks_from_details
from pullbox.ui.health_component_history import load_health_component_histories
from pullbox.ui.health_component_stats import (
    health_component_card_stats,
    health_component_detail_stats,
    health_component_sublabel,
)
from pullbox.ui.health_data import _HEALTH_HISTORY_SORT_DEFAULT
from pullbox.ui.health_presenters import (
    HealthCheckItemView,
    HealthComponentView,
    HealthFooterStripView,
    HealthGaugeView,
    HealthHistoryRowView,
    HealthMonitoringView,
    HealthScoreboardItemView,
    _health_card_tone,
    _health_led_tone,
    _health_pill_tone,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


HEALTH_COMPONENT_ORDER = (
    "database",
    "filesystem",
    "comicvine",
    "download_clients",
    "indexers",
    "scheduler",
    "system",
)


HEALTH_COMPONENT_LABELS = {
    "database": "Database",
    "filesystem": "Filesystem",
    "comicvine": "ComicVine API",
    "download_clients": "Download Clients",
    "indexers": "Indexers",
    "scheduler": "Scheduler",
    "system": "System Resources",
}


async def build_health_view(
    session: AsyncSession,
    *,
    components: list[object],
    overall_status: str,
    search_stats: object,
    gauge_offset: Callable[[float], float],
    relative_time_label: Callable[[datetime, datetime], str],
    current_time: datetime | None = None,
    detail_component_key: str | None = None,
    detail_history_page: int = 1,
    detail_history_per_page: int = 10,
    detail_history_sort: str = _HEALTH_HISTORY_SORT_DEFAULT,
    detail_history_search: str = "",
) -> HealthMonitoringView:
    """Build the health presenter for the mission-control page."""
    resolved_current_time = current_time or datetime.now(UTC)
    component_map = {
        typing_cast("Mapping[str, object]", component)["component"]: typing_cast(
            "Mapping[str, object]", component
        )
        for component in components
        if isinstance(component, Mapping)
    }

    history_bundle = await load_health_component_histories(
        session,
        component_keys=HEALTH_COMPONENT_ORDER,
        detail_component_key=detail_component_key,
        detail_history_page=detail_history_page,
        detail_history_per_page=detail_history_per_page,
        detail_history_sort=detail_history_sort,
        detail_history_search=detail_history_search,
        current_time=resolved_current_time,
        relative_time_label=relative_time_label,
    )

    healthy_count = 0
    degraded_count = 0
    unhealthy_count = 0
    component_views: list[HealthComponentView] = []

    for component_key in HEALTH_COMPONENT_ORDER:
        component = component_map.get(component_key)
        if component is None:
            component = {
                "component": component_key,
                "status": "unknown",
                "message": "Waiting for the next scheduled health check.",
                "response_time_ms": None,
                "last_checked": None,
                "details": {"checks": []},
            }
        status = str(component.get("status") or "unknown")
        if status == "healthy":
            healthy_count += 1
        elif status == "degraded":
            degraded_count += 1
        elif status == "unhealthy":
            unhealthy_count += 1

        checks = build_health_checks_from_details(component.get("details"))
        component_views.append(
            build_health_component_view(
                component_key=component_key,
                component=component,
                checks=checks,
                history=history_bundle.history_by_component.get(component_key, ()),
                history_page=history_bundle.page_by_component.get(component_key, 1),
                history_total_pages=history_bundle.total_pages_by_component.get(component_key, 1),
                history_total_count=history_bundle.total_count_by_component.get(component_key, 0),
                history_sort=history_bundle.sort_by_component.get(
                    component_key, _HEALTH_HISTORY_SORT_DEFAULT
                ),
                history_search_query=history_bundle.search_by_component.get(component_key, ""),
                current_time=resolved_current_time,
                relative_time_label=relative_time_label,
            )
        )

    total_monitors = len(component_views)
    total_checks = sum(max(1, len(component.checks)) for component in component_views)

    total_searches = int(getattr(search_stats, "total_searches", 0) or 0)
    total_matched = int(getattr(search_stats, "total_matched", 0) or 0)
    total_rejected = int(getattr(search_stats, "total_rejected", 0) or 0)
    total_results = int(getattr(search_stats, "total_results_parsed", 0) or 0)
    last_search_at_raw = getattr(search_stats, "last_search_at", None)
    last_search_at = (
        datetime.fromisoformat(last_search_at_raw)
        if isinstance(last_search_at_raw, str) and last_search_at_raw
        else None
    )
    total_evaluated = total_matched + total_rejected
    match_rate = round((total_matched / total_evaluated) * 100) if total_evaluated else 0
    rejection_rate = round((total_rejected / total_evaluated) * 100) if total_evaluated else 0

    gauges = (
        HealthGaugeView(
            key="healthy",
            label="Healthy",
            value_label=str(healthy_count),
            tone="success",
            stroke_offset=gauge_offset(healthy_count / total_monitors if total_monitors else 0),
        ),
        HealthGaugeView(
            key="degraded",
            label="Degraded",
            value_label=str(degraded_count),
            tone="warning",
            stroke_offset=gauge_offset(degraded_count / total_monitors if total_monitors else 0),
        ),
        HealthGaugeView(
            key="unhealthy",
            label="Unhealthy",
            value_label=str(unhealthy_count),
            tone="danger",
            stroke_offset=gauge_offset(unhealthy_count / total_monitors if total_monitors else 0),
        ),
    )

    scoreboard = (
        HealthScoreboardItemView(
            key="searches",
            label="Total Searches",
            value_label=str(total_searches),
            delta_label="Recorded",
        ),
        HealthScoreboardItemView(
            key="matched",
            label="Matched",
            value_label=str(total_matched),
            delta_label=f"{match_rate}% match rate" if total_evaluated else "No matches yet",
        ),
        HealthScoreboardItemView(
            key="rejected",
            label="Rejected",
            value_label=str(total_rejected),
            delta_label=(
                f"{rejection_rate}% rejection" if total_evaluated else "No rejects recorded"
            ),
        ),
        HealthScoreboardItemView(
            key="parsed",
            label="Results Parsed",
            value_label=str(total_results),
            delta_label="Observed",
        ),
        HealthScoreboardItemView(
            key="last-search",
            label="Last Search",
            value_label=(
                relative_time_label(last_search_at, resolved_current_time)
                if last_search_at is not None
                else "—"
            ),
            delta_label="Search activity",
        ),
    )

    footer = HealthFooterStripView(
        total_monitors=total_monitors,
        total_checks=total_checks,
        healthy_count=healthy_count,
        degraded_count=degraded_count,
        unhealthy_count=unhealthy_count,
    )

    return HealthMonitoringView(
        overall_status=overall_status,
        total_monitors=total_monitors,
        total_checks=total_checks,
        gauges=gauges,
        scoreboard=scoreboard,
        components=tuple(component_views),
        footer=footer,
    )


def build_health_component_view(
    *,
    component_key: str,
    component: Mapping[str, object],
    checks: tuple[HealthCheckItemView, ...],
    history: tuple[HealthHistoryRowView, ...],
    history_page: int,
    history_total_pages: int,
    history_total_count: int,
    history_sort: str,
    history_search_query: str,
    current_time: datetime,
    relative_time_label: Callable[[datetime, datetime], str],
) -> HealthComponentView:
    """Build one rendered health component card and detail view."""
    status = str(component.get("status") or "unknown")
    response_ms = component.get("response_time_ms")
    last_checked = component.get("last_checked")
    last_checked_dt = last_checked if isinstance(last_checked, datetime) else None
    display_name = HEALTH_COMPONENT_LABELS.get(
        component_key, component_key.replace("_", " ").title()
    )

    message = replace_duration_ms_tokens(
        str(component.get("message") or "No recent status message recorded.")
    )

    return HealthComponentView(
        key=component_key,
        component_key=component_key,
        display_name=display_name,
        detail_title=f"{display_name.upper()} DETAIL",
        status=status,
        status_label=status.capitalize(),
        pill_tone=_health_pill_tone(status),
        led_tone=_health_led_tone(status),
        card_tone=_health_card_tone(status),
        message=message,
        sublabel=health_component_sublabel(component_key, checks, component.get("details")),
        stats=health_component_card_stats(
            component_key,
            checks=checks,
            response_ms=response_ms,
            last_checked=last_checked_dt,
            current_time=current_time,
            details=component.get("details"),
            message=message,
            relative_time_label=relative_time_label,
        ),
        detail_stats=health_component_detail_stats(
            component_key,
            checks=checks,
            response_ms=response_ms,
            last_checked=last_checked_dt,
            current_time=current_time,
            details=component.get("details"),
            message=message,
            relative_time_label=relative_time_label,
        ),
        detail_variant="table" if component_key in {"download_clients", "indexers"} else "checks",
        checks=checks,
        history=history,
        history_page=history_page,
        history_total_pages=history_total_pages,
        history_total_count=history_total_count,
        history_sort=history_sort,
        history_search_query=history_search_query,
        history_base_path=f"/health/{component_key}",
    )


def select_health_component_view(
    health_view: HealthMonitoringView,
    component_key: str,
) -> HealthComponentView:
    """Return one component view or raise a 404 for an invalid key."""
    for component in health_view.components:
        if component.key == component_key:
            return component
    raise HTTPException(status_code=404, detail="Health component not found")
