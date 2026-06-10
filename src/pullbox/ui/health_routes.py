"""Health monitoring UI routes."""

from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import cast as typing_cast

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from pullbox.api.deps import AuthenticatedUser, DbSession
from pullbox.ui.health_check_items import build_health_checks_from_details
from pullbox.ui.health_component_stats import (
    health_attention_label,
    health_component_card_stats,
    health_component_detail_stats,
    health_component_sublabel,
)
from pullbox.ui.health_data import (
    _HEALTH_HISTORY_SORT_DEFAULT,
    _health_history_url,
    _load_health_data,
)
from pullbox.ui.health_data import _health_detail_checks as _health_detail_checks
from pullbox.ui.health_data import (
    _health_history_order_by as _health_history_order_by,
)
from pullbox.ui.health_data import (
    _health_history_prefers_subchecks as _health_history_prefers_subchecks,
)
from pullbox.ui.health_data import (
    _load_latest_health_subject_summary_rows as _load_latest_health_subject_summary_rows,
)
from pullbox.ui.health_data import (
    _normalize_health_history_sort as _normalize_health_history_sort,
)
from pullbox.ui.health_data import _parse_health_details_json as _parse_health_details_json
from pullbox.ui.health_footer_items import (
    build_health_component_footer_items as build_health_component_footer_items,
)
from pullbox.ui.health_overview_views import (
    build_health_component_view as _build_health_component_view_impl,
)
from pullbox.ui.health_overview_views import build_health_view as _build_health_view_impl
from pullbox.ui.health_overview_views import (
    select_health_component_view as _select_health_component_view_impl,
)
from pullbox.ui.health_placeholder_checks import (
    build_download_client_placeholder_checks,
    build_indexer_placeholder_checks,
    build_prowlarr_placeholder_checks,
)
from pullbox.ui.health_presenters import (
    HealthCheckItemView,
    HealthComponentStatView,
    HealthComponentView,
    HealthHistoryRowView,
    HealthMonitoringView,
    HealthSubjectSummaryView,
)
from pullbox.ui.health_presenters import (
    HealthFooterStripView as HealthFooterStripView,
)
from pullbox.ui.health_presenters import (
    HealthGaugeView as HealthGaugeView,
)
from pullbox.ui.health_presenters import (
    HealthScoreboardItemView as HealthScoreboardItemView,
)
from pullbox.ui.health_presenters import (
    _health_card_tone as _health_card_tone,
)
from pullbox.ui.health_presenters import (
    _health_check_response_label as _health_check_response_label,
)
from pullbox.ui.health_presenters import (
    _health_led_tone as _health_led_tone,
)
from pullbox.ui.health_presenters import (
    _health_parenthetical_next_line as _health_parenthetical_next_line,
)
from pullbox.ui.health_presenters import (
    _health_pill_tone as _health_pill_tone,
)
from pullbox.ui.health_presenters import _health_response_label as _health_response_label
from pullbox.ui.health_presenters import _mapping_text as _mapping_text
from pullbox.ui.health_presenters import _object_to_int as _object_to_int
from pullbox.ui.health_registry_rows import (
    build_download_client_registry_rows,
    build_indexer_registry_rows,
    download_client_endpoint_summary,
    health_response_or_dash,
    indexer_content_type_label,
    indexer_endpoint_summary,
    indexer_kind_detail_label,
    load_prowlarr_route_config,
)
from pullbox.ui.health_route_loaders import load_health_overview
from pullbox.ui.health_subject_detail_views import (
    build_download_client_detail_view,
    build_indexer_detail_view,
)

router = APIRouter()

__all__ = [
    "HealthCheckItemView",
    "HealthComponentStatView",
    "HealthComponentView",
    "HealthFooterStripView",
    "HealthGaugeView",
    "HealthHistoryRowView",
    "HealthMonitoringView",
    "HealthScoreboardItemView",
    "HealthSubjectSummaryView",
    "_build_health_component_footer_items",
    "_build_health_component_view",
    "_health_history_order_by",
    "_health_history_prefers_subchecks",
    "_health_history_url",
    "_load_health_data",
    "_normalize_health_history_sort",
    "_object_to_int",
]

_GetTemplates = Callable[[], Jinja2Templates]
_BuildContext = Callable[..., dict[str, object]]
_DashboardGaugeOffset = Callable[[float], float]
_RelativeTimeLabel = Callable[[datetime, datetime], str]
_DownloadClientLabel = Callable[[str], str]
_SidebarBadgeResponse = Callable[..., Response]
_LoadSidebarHealthCounts = Callable[[AsyncSession], Awaitable[tuple[int, int]]]

_get_templates: _GetTemplates | None = None
_build_context: _BuildContext | None = None
_dashboard_gauge_offset_impl: _DashboardGaugeOffset | None = None
_dashboard_relative_time_label_impl: _RelativeTimeLabel | None = None
_download_client_type_label_impl: _DownloadClientLabel | None = None
_sidebar_badge_response_impl: _SidebarBadgeResponse | None = None
_load_sidebar_health_counts_impl: _LoadSidebarHealthCounts | None = None


def configure_health_routes(
    *,
    get_templates: _GetTemplates,
    build_context: _BuildContext,
    dashboard_gauge_offset: _DashboardGaugeOffset,
    dashboard_relative_time_label: _RelativeTimeLabel,
    download_client_type_label: _DownloadClientLabel,
    sidebar_badge_response: _SidebarBadgeResponse,
    load_sidebar_health_counts: _LoadSidebarHealthCounts,
) -> None:
    """Provide shared UI runtime dependencies from the facade module."""
    global _get_templates, _build_context
    global _dashboard_gauge_offset_impl, _dashboard_relative_time_label_impl
    global _download_client_type_label_impl, _sidebar_badge_response_impl
    global _load_sidebar_health_counts_impl
    _get_templates = get_templates
    _build_context = build_context
    _dashboard_gauge_offset_impl = dashboard_gauge_offset
    _dashboard_relative_time_label_impl = dashboard_relative_time_label
    _download_client_type_label_impl = download_client_type_label
    _sidebar_badge_response_impl = sidebar_badge_response
    _load_sidebar_health_counts_impl = load_sidebar_health_counts


def _templates() -> Jinja2Templates:
    if _get_templates is None:
        msg = "health routes have not been configured with templates"
        raise RuntimeError(msg)
    return _get_templates()


def _ctx(request: Request, user: object | None = None, **kwargs: object) -> dict[str, object]:
    if _build_context is None:
        msg = "health routes have not been configured with a context builder"
        raise RuntimeError(msg)
    context: Mapping[str, object] = _build_context(request, user, **kwargs)
    return dict(context)


def _dashboard_gauge_offset(value: float) -> float:
    if _dashboard_gauge_offset_impl is None:
        msg = "health routes have not been configured with dashboard gauge helper"
        raise RuntimeError(msg)
    return _dashboard_gauge_offset_impl(value)


def _dashboard_relative_time_label(value: datetime, reference: datetime) -> str:
    if _dashboard_relative_time_label_impl is None:
        msg = "health routes have not been configured with relative time helper"
        raise RuntimeError(msg)
    return _dashboard_relative_time_label_impl(value, reference)


def _download_client_type_label(client_type: str) -> str:
    if _download_client_type_label_impl is None:
        msg = "health routes have not been configured with download client label helper"
        raise RuntimeError(msg)
    return _download_client_type_label_impl(client_type)


def _sidebar_badge_response(
    request: Request,
    user: object | None,
    *,
    count: int,
    badge_classes: str,
) -> Response:
    if _sidebar_badge_response_impl is None:
        msg = "health routes have not been configured with sidebar badge helper"
        raise RuntimeError(msg)
    return _sidebar_badge_response_impl(
        request,
        user,
        count=count,
        badge_classes=badge_classes,
    )


async def _load_sidebar_health_counts(session: AsyncSession) -> tuple[int, int]:
    if _load_sidebar_health_counts_impl is None:
        msg = "health routes have not been configured with sidebar health counts"
        raise RuntimeError(msg)
    return await _load_sidebar_health_counts_impl(session)


async def _load_health_overview(
    session: AsyncSession,
    **health_view_options: object,
) -> tuple[str, HealthMonitoringView]:
    from pullbox.services.search_service import get_search_stats

    result = await load_health_overview(
        session,
        load_health_data=_load_health_data,
        get_search_stats=get_search_stats,
        build_health_view=_build_health_view,
        **health_view_options,
    )
    return result.overall_status, typing_cast("HealthMonitoringView", result.health_view)


@router.get("/health", response_class=HTMLResponse, include_in_schema=False)
async def health_page(
    request: Request,
    user: AuthenticatedUser,
    session: DbSession,
) -> Response:
    """Render the health monitoring dashboard."""
    overall_status, health_view = await _load_health_overview(session)
    return _templates().TemplateResponse(
        request,
        "pages/health.html",
        _ctx(
            request,
            user,
            overall_status=overall_status,
            health_view=health_view,
        ),
    )


@router.get("/health/status", response_class=HTMLResponse, include_in_schema=False)
async def health_status_partial(
    request: Request,
    user: AuthenticatedUser,
    session: DbSession,
) -> Response:
    """Return the health status cards partial for HTMX polling."""
    overall_status, health_view = await _load_health_overview(session)
    return _templates().TemplateResponse(
        request,
        "partials/health_status_region.html",
        _ctx(
            request,
            user,
            overall_status=overall_status,
            health_view=health_view,
        ),
    )


@router.get("/health/badge", response_class=HTMLResponse, include_in_schema=False)
async def health_badge_partial(
    request: Request,
    user: AuthenticatedUser,
    session: DbSession,
) -> Response:
    """Return the health nav badge partial for HTMX polling."""
    degraded, unhealthy = await _load_sidebar_health_counts(session)
    return _sidebar_badge_response(
        request,
        user,
        count=degraded + unhealthy,
        badge_classes="count-badge-error" if unhealthy > 0 else "count-badge-warning",
    )


@router.get("/health/download_clients/status", response_class=HTMLResponse, include_in_schema=False)
async def health_download_clients_status_partial(
    request: Request,
    user: AuthenticatedUser,
    session: DbSession,
) -> Response:
    """Return the download-clients registry partial for HTMX polling."""
    overall_status, health_view = await _load_health_overview(session)
    health_component = _select_health_component_view(health_view, "download_clients")
    health_client_rows = await _build_download_client_registry_rows(session)
    response = _templates().TemplateResponse(
        request,
        "partials/health_download_clients_content_bundle.html",
        _ctx(
            request,
            user,
            overall_status=overall_status,
            health_component=health_component,
            health_client_rows=health_client_rows,
            health_detail_footer_items=_build_health_component_footer_items(health_component),
        ),
    )
    response.headers["HX-Replace-Url"] = "/health/download_clients"
    return response


@router.get("/health/download_clients", response_class=HTMLResponse, include_in_schema=False)
async def health_download_clients_page(
    request: Request,
    user: AuthenticatedUser,
    session: DbSession,
) -> Response:
    """Render the download-clients health registry page."""
    overall_status, health_view = await _load_health_overview(session)
    health_component = _select_health_component_view(health_view, "download_clients")
    return _templates().TemplateResponse(
        request,
        "pages/health_download_clients.html",
        _ctx(
            request,
            user,
            overall_status=overall_status,
            health_component=health_component,
            health_client_rows=await _build_download_client_registry_rows(session),
            health_detail_footer_items=_build_health_component_footer_items(health_component),
        ),
    )


@router.get(
    "/health/download_clients/{subject_key}/status",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def health_download_client_status_partial(
    request: Request,
    user: AuthenticatedUser,
    session: DbSession,
    subject_key: str,
    history_page: int = Query(1, ge=1),
    sort: str = Query("-checked_at"),
    search: str = Query(""),
) -> Response:
    """Return the single download-client health detail partial for HTMX polling."""
    _components, overall_status = await _load_health_data(session)
    health_component = await _build_download_client_detail_view(
        session,
        subject_key=subject_key,
        current_time=datetime.now(UTC),
        history_page=history_page,
        history_sort=sort,
        history_search=search,
    )
    response = _templates().TemplateResponse(
        request,
        "partials/health_component_content_bundle.html",
        _ctx(
            request,
            user,
            overall_status=overall_status,
            health_component=health_component,
            health_detail_footer_items=_build_health_component_footer_items(health_component),
        ),
    )
    response.headers["HX-Replace-Url"] = _health_history_url(
        "download_clients",
        base_path=health_component.history_base_path,
        search_query=health_component.history_search_query,
        sort=health_component.history_sort,
        page=health_component.history_page,
    )
    return response


@router.get(
    "/health/download_clients/{subject_key}",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def health_download_client_page(
    request: Request,
    user: AuthenticatedUser,
    session: DbSession,
    subject_key: str,
    history_page: int = Query(1, ge=1),
    sort: str = Query("-checked_at"),
    search: str = Query(""),
) -> Response:
    """Render the dedicated detail page for one download client health subject."""
    _components, overall_status = await _load_health_data(session)
    health_component = await _build_download_client_detail_view(
        session,
        subject_key=subject_key,
        current_time=datetime.now(UTC),
        history_page=history_page,
        history_sort=sort,
        history_search=search,
    )
    return _templates().TemplateResponse(
        request,
        "pages/health_component.html",
        _ctx(
            request,
            user,
            overall_status=overall_status,
            health_component=health_component,
            health_detail_footer_items=_build_health_component_footer_items(health_component),
        ),
    )


@router.get("/health/indexers/status", response_class=HTMLResponse, include_in_schema=False)
async def health_indexers_status_partial(
    request: Request,
    user: AuthenticatedUser,
    session: DbSession,
) -> Response:
    """Return the split indexer registry partial for HTMX polling."""
    overall_status, health_view = await _load_health_overview(session)
    health_component = _select_health_component_view(health_view, "indexers")
    prowlarr_row, health_indexer_rows = await _build_indexer_registry_rows(session)
    response = _templates().TemplateResponse(
        request,
        "partials/health_indexers_content_bundle.html",
        _ctx(
            request,
            user,
            overall_status=overall_status,
            health_component=health_component,
            health_prowlarr_row=prowlarr_row,
            health_indexer_rows=health_indexer_rows,
            health_detail_footer_items=_build_health_component_footer_items(health_component),
        ),
    )
    response.headers["HX-Replace-Url"] = "/health/indexers"
    return response


@router.get("/health/indexers", response_class=HTMLResponse, include_in_schema=False)
async def health_indexers_page(
    request: Request,
    user: AuthenticatedUser,
    session: DbSession,
) -> Response:
    """Render the split indexer registry page."""
    overall_status, health_view = await _load_health_overview(session)
    health_component = _select_health_component_view(health_view, "indexers")
    prowlarr_row, health_indexer_rows = await _build_indexer_registry_rows(session)
    return _templates().TemplateResponse(
        request,
        "pages/health_indexers.html",
        _ctx(
            request,
            user,
            overall_status=overall_status,
            health_component=health_component,
            health_prowlarr_row=prowlarr_row,
            health_indexer_rows=health_indexer_rows,
            health_detail_footer_items=_build_health_component_footer_items(health_component),
        ),
    )


@router.get(
    "/health/indexers/{subject_key}/status",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def health_indexer_status_partial(
    request: Request,
    user: AuthenticatedUser,
    session: DbSession,
    subject_key: str,
    history_page: int = Query(1, ge=1),
    sort: str = Query("-checked_at"),
    search: str = Query(""),
) -> Response:
    """Return one indexer-subject health detail partial for HTMX polling."""
    _components, overall_status = await _load_health_data(session)
    health_component = await _build_indexer_detail_view(
        session,
        subject_key=subject_key,
        current_time=datetime.now(UTC),
        history_page=history_page,
        history_sort=sort,
        history_search=search,
    )
    response = _templates().TemplateResponse(
        request,
        "partials/health_component_content_bundle.html",
        _ctx(
            request,
            user,
            overall_status=overall_status,
            health_component=health_component,
            health_detail_footer_items=_build_health_component_footer_items(health_component),
        ),
    )
    response.headers["HX-Replace-Url"] = _health_history_url(
        "indexers",
        base_path=health_component.history_base_path,
        search_query=health_component.history_search_query,
        sort=health_component.history_sort,
        page=health_component.history_page,
    )
    return response


@router.get("/health/indexers/{subject_key}", response_class=HTMLResponse, include_in_schema=False)
async def health_indexer_page(
    request: Request,
    user: AuthenticatedUser,
    session: DbSession,
    subject_key: str,
    history_page: int = Query(1, ge=1),
    sort: str = Query("-checked_at"),
    search: str = Query(""),
) -> Response:
    """Render the dedicated detail page for one indexer subject."""
    _components, overall_status = await _load_health_data(session)
    health_component = await _build_indexer_detail_view(
        session,
        subject_key=subject_key,
        current_time=datetime.now(UTC),
        history_page=history_page,
        history_sort=sort,
        history_search=search,
    )
    return _templates().TemplateResponse(
        request,
        "pages/health_component.html",
        _ctx(
            request,
            user,
            overall_status=overall_status,
            health_component=health_component,
            health_detail_footer_items=_build_health_component_footer_items(health_component),
        ),
    )


@router.get("/health/{component_key}/status", response_class=HTMLResponse, include_in_schema=False)
async def health_component_status_partial(
    request: Request,
    user: AuthenticatedUser,
    session: DbSession,
    component_key: str,
    history_page: int = Query(1, ge=1),
    sort: str = Query("-checked_at"),
    search: str = Query(""),
) -> Response:
    """Return the single-component health detail partial for HTMX polling."""
    overall_status, health_view = await _load_health_overview(
        session,
        detail_component_key=component_key,
        detail_history_page=history_page,
        detail_history_sort=sort,
        detail_history_search=search,
    )
    health_component = _select_health_component_view(health_view, component_key)
    response = _templates().TemplateResponse(
        request,
        "partials/health_component_content_bundle.html",
        _ctx(
            request,
            user,
            overall_status=overall_status,
            health_view=health_view,
            health_component=health_component,
            health_detail_footer_items=_build_health_component_footer_items(health_component),
        ),
    )
    response.headers["HX-Replace-Url"] = _health_history_url(
        component_key,
        search_query=health_component.history_search_query,
        sort=health_component.history_sort,
        page=health_component.history_page,
    )
    return response


@router.get("/health/{component_key}", response_class=HTMLResponse, include_in_schema=False)
async def health_component_page(
    request: Request,
    user: AuthenticatedUser,
    session: DbSession,
    component_key: str,
    history_page: int = Query(1, ge=1),
    sort: str = Query("-checked_at"),
    search: str = Query(""),
) -> Response:
    """Render the dedicated drill-down page for a health component."""
    overall_status, health_view = await _load_health_overview(
        session,
        detail_component_key=component_key,
        detail_history_page=history_page,
        detail_history_sort=sort,
        detail_history_search=search,
    )
    health_component = _select_health_component_view(health_view, component_key)
    return _templates().TemplateResponse(
        request,
        "pages/health_component.html",
        _ctx(
            request,
            user,
            overall_status=overall_status,
            health_view=health_view,
            health_component=health_component,
            health_detail_footer_items=_build_health_component_footer_items(health_component),
        ),
    )


async def _build_health_view(
    session: AsyncSession,
    *,
    components: list[object],
    overall_status: str,
    search_stats: object,
    detail_component_key: str | None = None,
    detail_history_page: int = 1,
    detail_history_per_page: int = 10,
    detail_history_sort: str = _HEALTH_HISTORY_SORT_DEFAULT,
    detail_history_search: str = "",
) -> HealthMonitoringView:
    """Build the health presenter for the mission-control page."""
    return await _build_health_view_impl(
        session,
        components=components,
        overall_status=overall_status,
        search_stats=search_stats,
        detail_component_key=detail_component_key,
        detail_history_page=detail_history_page,
        detail_history_per_page=detail_history_per_page,
        detail_history_sort=detail_history_sort,
        detail_history_search=detail_history_search,
        gauge_offset=_dashboard_gauge_offset,
        relative_time_label=_dashboard_relative_time_label,
    )


def _build_health_component_view(
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
) -> HealthComponentView:
    """Build one rendered health component card and detail view."""
    return _build_health_component_view_impl(
        component_key=component_key,
        component=component,
        checks=checks,
        history=history,
        history_page=history_page,
        history_total_pages=history_total_pages,
        history_total_count=history_total_count,
        history_sort=history_sort,
        history_search_query=history_search_query,
        current_time=current_time,
        relative_time_label=_dashboard_relative_time_label,
    )


def _select_health_component_view(
    health_view: HealthMonitoringView,
    component_key: str,
) -> HealthComponentView:
    """Return one component view or raise a 404 for an invalid key."""
    return _select_health_component_view_impl(health_view, component_key)


def _build_health_component_footer_items(
    component: HealthComponentView,
) -> tuple[dict[str, str | None], ...]:
    """Build footer dock values for the single-component detail page."""
    return build_health_component_footer_items(component)


def _download_client_endpoint_summary(url: str) -> tuple[str, str, str]:
    """Return protocol, host, and port labels for a client URL."""
    return download_client_endpoint_summary(url)


def _download_client_placeholder_checks() -> tuple[HealthCheckItemView, ...]:
    """Return placeholder checks for a client without recorded health yet."""
    return build_download_client_placeholder_checks()


def _health_response_or_dash(response_ms: object) -> str:
    """Format a response time unless it is missing or effectively unmeasured."""
    return health_response_or_dash(response_ms)


async def _load_prowlarr_route_config(session: AsyncSession) -> str | None:
    """Return the configured Prowlarr URL when both URL and API key are present."""
    return await load_prowlarr_route_config(session)


def _indexer_endpoint_summary(url: str) -> tuple[str, str, str]:
    """Return protocol, host, and port labels for an indexer URL."""
    return indexer_endpoint_summary(url)


def _indexer_kind_detail_label(indexer_type: str) -> str:
    """Return the API family label shown under an indexer name."""
    return indexer_kind_detail_label(indexer_type)


def _indexer_content_type_label(indexer_type: str) -> str:
    """Return the content family label shown in the Type column."""
    return indexer_content_type_label(indexer_type)


def _prowlarr_placeholder_checks() -> tuple[HealthCheckItemView, ...]:
    """Return placeholder checks for Prowlarr before any health data exists."""
    return build_prowlarr_placeholder_checks()


def _indexer_placeholder_checks() -> tuple[HealthCheckItemView, ...]:
    """Return placeholder checks for an indexer before any health data exists."""
    return build_indexer_placeholder_checks()


async def _build_download_client_registry_rows(
    session: AsyncSession,
) -> tuple[HealthSubjectSummaryView, ...]:
    """Build the Download Clients registry rows for the list-style health page."""
    return await build_download_client_registry_rows(
        session,
        current_time=datetime.now(UTC),
        relative_time_label=_dashboard_relative_time_label,
        download_client_type_label=_download_client_type_label,
    )


async def _build_indexer_registry_rows(
    session: AsyncSession,
) -> tuple[HealthSubjectSummaryView | None, tuple[HealthSubjectSummaryView, ...]]:
    """Build the split proxy/indexer registry rows for the indexers page."""
    return await build_indexer_registry_rows(
        session,
        current_time=datetime.now(UTC),
        relative_time_label=_dashboard_relative_time_label,
    )


async def _build_download_client_detail_view(
    session: AsyncSession,
    *,
    subject_key: str,
    current_time: datetime,
    history_page: int,
    history_sort: str,
    history_search: str,
) -> HealthComponentView:
    """Build a detail-page presenter for one download client subject."""
    return await build_download_client_detail_view(
        session,
        subject_key=subject_key,
        current_time=current_time,
        history_page=history_page,
        history_sort=history_sort,
        history_search=history_search,
        relative_time_label=_dashboard_relative_time_label,
        download_client_type_label=_download_client_type_label,
    )


async def _build_indexer_detail_view(
    session: AsyncSession,
    *,
    subject_key: str,
    current_time: datetime,
    history_page: int,
    history_sort: str,
    history_search: str,
) -> HealthComponentView:
    """Build a detail-page presenter for Prowlarr or one indexer subject."""
    return await build_indexer_detail_view(
        session,
        subject_key=subject_key,
        current_time=current_time,
        history_page=history_page,
        history_sort=history_sort,
        history_search=history_search,
        relative_time_label=_dashboard_relative_time_label,
    )


def _health_checks_from_details(details: object) -> tuple[HealthCheckItemView, ...]:
    """Extract normalized health checks from a component details payload."""
    return build_health_checks_from_details(details)


def _health_component_card_stats(
    component_key: str,
    *,
    checks: tuple[HealthCheckItemView, ...],
    response_ms: object,
    last_checked: datetime | None,
    current_time: datetime,
    details: object,
    message: str,
) -> tuple[HealthComponentStatView, ...]:
    """Return the compact stats shown on component cards."""
    return health_component_card_stats(
        component_key,
        checks=checks,
        response_ms=response_ms,
        last_checked=last_checked,
        current_time=current_time,
        details=details,
        message=message,
        relative_time_label=_dashboard_relative_time_label,
    )


def _health_component_detail_stats(
    component_key: str,
    *,
    checks: tuple[HealthCheckItemView, ...],
    response_ms: object,
    last_checked: datetime | None,
    current_time: datetime,
    details: object,
    message: str,
) -> tuple[HealthComponentStatView, ...]:
    """Return the larger stat strip shown in component detail."""
    return health_component_detail_stats(
        component_key,
        checks=checks,
        response_ms=response_ms,
        last_checked=last_checked,
        current_time=current_time,
        details=details,
        message=message,
        relative_time_label=_dashboard_relative_time_label,
    )


def _health_attention_label(
    checks: tuple[HealthCheckItemView, ...],
    *,
    down_noun: str,
) -> str:
    """Summarize attention needed for grouped health components."""
    return health_attention_label(checks, down_noun=down_noun)


def _health_component_sublabel(
    component_key: str,
    checks: tuple[HealthCheckItemView, ...],
    details: object,
) -> str:
    """Return the compact monospace sublabel for a health component card."""
    return health_component_sublabel(component_key, checks, details)
