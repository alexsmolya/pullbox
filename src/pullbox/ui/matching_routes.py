"""Matching queue UI routes and HTMX partials."""

from collections.abc import Callable, Mapping

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload
from starlette.responses import Response

from pullbox.api.deps import AuthenticatedUser, DbSession
from pullbox.core.db_utils import escape_like
from pullbox.models.issue import Issue
from pullbox.models.library import LibraryFile, MatchConfidence
from pullbox.models.series import Series

queue_router = APIRouter()
htmx_router = APIRouter()

_MATCHING_PER_PAGE = 50

_GetTemplates = Callable[[], Jinja2Templates]
_BuildContext = Callable[..., dict[str, object]]

_get_templates: _GetTemplates | None = None
_build_context: _BuildContext | None = None


def configure_matching_routes(
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
        msg = "matching routes have not been configured with templates"
        raise RuntimeError(msg)
    return _get_templates()


def _ctx(request: Request, user: object | None = None, **kwargs: object) -> dict[str, object]:
    if _build_context is None:
        msg = "matching routes have not been configured with a context builder"
        raise RuntimeError(msg)
    context: Mapping[str, object] = _build_context(request, user, **kwargs)
    return dict(context)


@queue_router.get("/library/matching", response_class=HTMLResponse, include_in_schema=False)
async def matching_queue(
    request: Request,
    user: AuthenticatedUser,
    session: DbSession,
    page: int = Query(1, ge=1),
) -> Response:
    """Render the matching queue page with unmatched library files."""
    total: int = (
        await session.execute(
            select(func.count(LibraryFile.id)).where(
                LibraryFile.match_confidence == MatchConfidence.UNMATCHED
            )
        )
    ).scalar_one()
    total_pages = max(1, (total + _MATCHING_PER_PAGE - 1) // _MATCHING_PER_PAGE)
    page = min(page, total_pages)
    offset = (page - 1) * _MATCHING_PER_PAGE

    result = await session.execute(
        select(LibraryFile)
        .options(joinedload(LibraryFile.library_root))
        .where(LibraryFile.match_confidence == MatchConfidence.UNMATCHED)
        .order_by(LibraryFile.file_name)
        .limit(_MATCHING_PER_PAGE)
        .offset(offset)
    )
    files = list(result.unique().scalars().all())

    return _templates().TemplateResponse(
        request,
        "pages/matching_queue.html",
        _ctx(
            request,
            user,
            files=files,
            total=total,
            page=page,
            total_pages=total_pages,
        ),
    )


@htmx_router.get("/htmx/matching/series", response_class=HTMLResponse, include_in_schema=False)
async def htmx_matching_series_search(
    request: Request,
    user: AuthenticatedUser,
    session: DbSession,
    q: str | None = Query(None),
) -> Response:
    """Search local series for manual matching - HTMX partial."""
    if not q or len(q.strip()) < 2:
        return _templates().TemplateResponse(
            request,
            "partials/matching_series_results.html",
            _ctx(request, user),
        )

    result = await session.execute(
        select(Series)
        .options(joinedload(Series.publisher))
        .where(Series.title.ilike(f"%{escape_like(q.strip())}%"))
        .order_by(Series.sort_title)
        .limit(20)
    )
    series_list = list(result.unique().scalars().all())

    return _templates().TemplateResponse(
        request,
        "partials/matching_series_results.html",
        _ctx(request, user, series_list=series_list, query=q),
    )


@htmx_router.get("/htmx/matching/issues", response_class=HTMLResponse, include_in_schema=False)
async def htmx_matching_issues(
    request: Request,
    user: AuthenticatedUser,
    session: DbSession,
    series_id: int = Query(...),
) -> Response:
    """List issues for a series for manual matching - HTMX partial."""
    series_result = await session.execute(select(Series.title).where(Series.id == series_id))
    series_title = series_result.scalar_one_or_none() or "Unknown"

    result = await session.execute(
        select(Issue).where(Issue.series_id == series_id).order_by(Issue.issue_number.asc())
    )
    issues = list(result.scalars().all())

    return _templates().TemplateResponse(
        request,
        "partials/matching_issues.html",
        _ctx(request, user, issues=issues, series_title=series_title, series_id=series_id),
    )
