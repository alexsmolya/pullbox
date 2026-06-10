"""Blocklist UI routes and context loaders."""

from collections.abc import Callable, Mapping

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from pullbox.api.deps import AuthenticatedUser, DbSession
from pullbox.models.blocklist import BlocklistReason
from pullbox.services.blocklist_service import BlocklistService

router = APIRouter()

_BLOCKLIST_PER_PAGE = 25
_BLOCKLIST_SORT_OPTIONS = {"title", "reason", "release_group", "created_at", "series"}

_GetTemplates = Callable[[], Jinja2Templates]
_BuildContext = Callable[..., dict[str, object]]

_get_templates: _GetTemplates | None = None
_build_context: _BuildContext | None = None


def configure_blocklist_routes(
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
        msg = "blocklist routes have not been configured with templates"
        raise RuntimeError(msg)
    return _get_templates()


def _ctx(request: Request, user: object | None = None, **kwargs: object) -> dict[str, object]:
    if _build_context is None:
        msg = "blocklist routes have not been configured with a context builder"
        raise RuntimeError(msg)
    context: Mapping[str, object] = _build_context(request, user, **kwargs)
    return dict(context)


def normalize_blocklist_sort(sort: str | None) -> str:
    """Return a valid blocklist sort key."""
    if not sort:
        return "-created_at"
    desc = sort.startswith("-")
    field = sort.lstrip("-")
    if field not in _BLOCKLIST_SORT_OPTIONS:
        return "-created_at"
    return ("-" if desc else "") + field


def parse_blocklist_reason(
    reason: str | None,
) -> tuple[BlocklistReason | None, str]:
    """Return a valid blocklist reason enum for filtering."""
    if not reason:
        return None, ""

    try:
        reason_enum = BlocklistReason(reason)
    except ValueError:
        return None, ""
    return reason_enum, reason_enum.value


async def load_blocklist_context(
    session: AsyncSession,
    *,
    reason: str | None,
    search: str | None,
    sort: str,
    page: int,
) -> dict[str, object]:
    """Load the filtered blocklist results for the page shell."""
    reason_enum, normalized_reason = parse_blocklist_reason(reason)
    normalized_sort = normalize_blocklist_sort(sort)
    requested_page = max(1, page)

    entries, total = await BlocklistService.list_entries(
        session,
        limit=_BLOCKLIST_PER_PAGE,
        offset=(requested_page - 1) * _BLOCKLIST_PER_PAGE,
        reason=reason_enum,
        search=search,
        sort=normalized_sort,
    )

    total_pages = max(1, (total + _BLOCKLIST_PER_PAGE - 1) // _BLOCKLIST_PER_PAGE)
    page = min(requested_page, total_pages)

    if page != requested_page:
        entries, total = await BlocklistService.list_entries(
            session,
            limit=_BLOCKLIST_PER_PAGE,
            offset=(page - 1) * _BLOCKLIST_PER_PAGE,
            reason=reason_enum,
            search=search,
            sort=normalized_sort,
        )

    grouped_counts = await BlocklistService.count_entries_by_reason(
        session,
        reason=reason_enum,
        search=search,
    )
    failed_count = grouped_counts.get(BlocklistReason.FAILED, 0)
    rejected_count = grouped_counts.get(BlocklistReason.REJECTED, 0)
    manual_count = grouped_counts.get(BlocklistReason.MANUAL, 0)

    return {
        "entries": entries,
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "reason_filter": normalized_reason,
        "search_query": search or "",
        "sort": normalized_sort,
        "failed_count": failed_count,
        "rejected_count": rejected_count,
        "manual_count": manual_count,
    }


@router.get("/blocklist", response_class=HTMLResponse, include_in_schema=False)
async def blocklist_page(
    request: Request,
    user: AuthenticatedUser,
    session: DbSession,
    reason: str | None = Query(None),
    search: str | None = Query(None),
    sort: str = Query("-created_at"),
    page: int = Query(1, ge=1),
) -> Response:
    """Render the blocklist management page."""
    ctx = _ctx(
        request,
        user,
        **await load_blocklist_context(
            session,
            reason=reason,
            search=search,
            sort=sort,
            page=page,
        ),
    )

    if request.headers.get("HX-Request"):
        return _templates().TemplateResponse(
            request,
            "partials/blocklist_content_bundle.html",
            ctx,
        )

    return _templates().TemplateResponse(request, "pages/blocklist.html", ctx)


@router.get("/htmx/blocklist", response_class=HTMLResponse, include_in_schema=False)
async def htmx_blocklist(
    request: Request,
    user: AuthenticatedUser,
    session: DbSession,
    reason: str | None = Query(None),
    search: str | None = Query(None),
    sort: str = Query("-created_at"),
    page: int = Query(1, ge=1),
) -> Response:
    """Return the blocklist body partial for HTMX swap."""
    return _templates().TemplateResponse(
        request,
        "partials/blocklist_results_body.html",
        _ctx(
            request,
            user,
            **await load_blocklist_context(
                session,
                reason=reason,
                search=search,
                sort=sort,
                page=page,
            ),
        ),
    )


@router.get(
    "/htmx/blocklist/{entry_id}/error-detail",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def htmx_blocklist_error_detail(
    request: Request,
    entry_id: int,
    user: AuthenticatedUser,
    session: DbSession,
) -> Response:
    """Render a blocklist entry's error detail only after its row is expanded."""
    entry = await BlocklistService.get_entry(session, entry_id)
    if entry is None or not entry.error_message:
        raise HTTPException(status_code=404, detail="Blocklist error detail not found")

    return _templates().TemplateResponse(
        request,
        "partials/blocklist_error_detail.html",
        _ctx(request, user, entry=entry),
    )
