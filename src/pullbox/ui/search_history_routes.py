"""Search history UI route and loaders."""

from collections.abc import Callable, Mapping
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import ColumnElement, String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from pullbox.api.deps import AuthenticatedUser, DbSession
from pullbox.core.db_utils import escape_like
from pullbox.models.search_log import SearchLog

router = APIRouter()

_SEARCH_HISTORY_PER_PAGE = 25

_GetTemplates = Callable[[], Jinja2Templates]
_BuildContext = Callable[..., dict[str, object]]

_get_templates: _GetTemplates | None = None
_build_context: _BuildContext | None = None


def configure_search_history_routes(
    *,
    get_templates: _GetTemplates,
    build_context: _BuildContext,
) -> None:
    """Provide shared UI runtime dependencies from the facade module."""
    global _get_templates, _build_context
    _get_templates = get_templates
    _build_context = build_context


def _templates() -> Jinja2Templates:
    if _get_templates is None:
        msg = "search history routes have not been configured with templates"
        raise RuntimeError(msg)
    return _get_templates()


def _ctx(request: Request, user: object | None = None, **kwargs: object) -> dict[str, object]:
    if _build_context is None:
        msg = "search history routes have not been configured with a context builder"
        raise RuntimeError(msg)
    context: Mapping[str, object] = _build_context(request, user, **kwargs)
    return dict(context)


async def load_search_history_context(
    session: AsyncSession,
    *,
    search_type_filter: str | None,
    confidence_filter: str | None,
    search_query: str | None,
    sort: str,
    requested_page: int,
) -> dict[str, object]:
    """Load search history rows with stable filtering/sorting/pagination."""
    aggregate_q = select(
        func.count(SearchLog.id),
        func.coalesce(func.sum(SearchLog.results_grabbed), 0),
        func.coalesce(func.sum(SearchLog.results_queued), 0),
        func.coalesce(func.sum(SearchLog.results_rejected), 0),
    )
    rows_q = select(SearchLog)
    normalized_type_filter = (search_type_filter or "").strip()
    normalized_confidence_filter = (confidence_filter or "").strip().lower()
    normalized_search_query = (search_query or "").strip()

    if normalized_type_filter:
        aggregate_q = aggregate_q.where(SearchLog.search_type == normalized_type_filter)
        rows_q = rows_q.where(SearchLog.search_type == normalized_type_filter)

    if normalized_confidence_filter:
        confidence_clause: ColumnElement[bool]
        if normalized_confidence_filter == "none":
            confidence_clause = SearchLog.best_confidence.is_(None)
        else:
            confidence_clause = SearchLog.best_confidence == normalized_confidence_filter
        aggregate_q = aggregate_q.where(confidence_clause)
        rows_q = rows_q.where(confidence_clause)

    if normalized_search_query:
        search_term = f"%{escape_like(normalized_search_query)}%"
        search_clause = or_(
            SearchLog.series_title.ilike(search_term),
            cast(SearchLog.issue_number, String).ilike(search_term),
        )
        aggregate_q = aggregate_q.where(search_clause)
        rows_q = rows_q.where(search_clause)

    sort_map = {
        "created_at": SearchLog.created_at,
        "series_title": SearchLog.series_title,
        "search_type": SearchLog.search_type,
        "results_found": SearchLog.results_found,
        "results_grabbed": SearchLog.results_grabbed,
        "results_queued": SearchLog.results_queued,
        "results_rejected": SearchLog.results_rejected,
        "best_confidence": SearchLog.best_confidence,
    }
    descending = sort.startswith("-")
    sort_field = sort.lstrip("-")
    col = sort_map.get(sort_field, SearchLog.created_at)
    rows_q = rows_q.order_by(col.desc() if descending else col.asc())

    total, grabbed_total, queued_total, rejected_total = (await session.execute(aggregate_q)).one()
    total = int(total)
    total_pages = max(1, (total + _SEARCH_HISTORY_PER_PAGE - 1) // _SEARCH_HISTORY_PER_PAGE)
    page = min(requested_page, total_pages)
    offset = (page - 1) * _SEARCH_HISTORY_PER_PAGE

    result = await session.execute(rows_q.limit(_SEARCH_HISTORY_PER_PAGE).offset(offset))
    search_logs = list(result.unique().scalars().all())
    has_active_logs = any((log.details or {}).get("run_state") == "running" for log in search_logs)

    refresh_params: dict[str, str] = {}
    if normalized_type_filter:
        refresh_params["search_type"] = normalized_type_filter
    if normalized_confidence_filter:
        refresh_params["confidence"] = normalized_confidence_filter
    if normalized_search_query:
        refresh_params["search"] = normalized_search_query
    if sort and sort != "-created_at":
        refresh_params["sort"] = sort
    if page > 1:
        refresh_params["page"] = str(page)
    refresh_url = "/search-history"
    if refresh_params:
        refresh_url += "?" + urlencode(refresh_params)

    return {
        "search_logs": search_logs,
        "search_log_total": total,
        "search_log_pages": total_pages,
        "search_log_grabbed_total": int(grabbed_total or 0),
        "search_log_queued_total": int(queued_total or 0),
        "search_log_rejected_total": int(rejected_total or 0),
        "search_type_filter": normalized_type_filter,
        "confidence_filter": normalized_confidence_filter,
        "search_query": normalized_search_query,
        "sort": sort,
        "page": page,
        "search_history_has_active_logs": has_active_logs,
        "search_history_refresh_url": refresh_url,
    }


@router.get("/search-history", response_class=HTMLResponse, include_in_schema=False)
async def search_history_page(
    request: Request,
    user: AuthenticatedUser,
    session: DbSession,
    search_type_filter: str | None = Query(None, alias="search_type"),
    confidence_filter: str | None = Query(None, alias="confidence"),
    search_query: str | None = Query(None, alias="search"),
    sort: str = Query("-created_at"),
    page: int = Query(1, ge=1),
) -> Response:
    """Render the search history page (search log records)."""
    ctx = _ctx(
        request,
        user,
        **await load_search_history_context(
            session,
            search_type_filter=search_type_filter,
            confidence_filter=confidence_filter,
            search_query=search_query,
            sort=sort,
            requested_page=page,
        ),
    )

    if request.headers.get("HX-Request"):
        return _templates().TemplateResponse(
            request,
            "partials/search_history_content_bundle.html",
            ctx,
        )

    return _templates().TemplateResponse(request, "pages/search_history.html", ctx)


@router.get(
    "/htmx/search-history/logs/{log_id}/detail",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def search_history_log_detail(
    request: Request,
    log_id: int,
    user: AuthenticatedUser,
    session: DbSession,
) -> Response:
    """Render heavy search diagnostics only after a history row is expanded."""
    log = await session.get(SearchLog, log_id)
    if log is None:
        raise HTTPException(status_code=404, detail="Search history log not found")
    return _templates().TemplateResponse(
        request,
        "partials/search_history_log_detail.html",
        _ctx(request, user, log=log),
    )
