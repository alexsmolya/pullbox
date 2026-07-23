"""Series and issue detail UI routes."""

from collections.abc import Callable, Mapping
from typing import Annotated
from urllib.parse import unquote

import structlog
from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload
from starlette.responses import Response

from pullbox.api.deps import AuthenticatedUser, DbSession
from pullbox.models.issue import Issue, IssueStatus
from pullbox.models.library import LibraryFile
from pullbox.models.series import Series
from pullbox.services.series_service import SeriesService
from pullbox.ui.comicvine_series_search import wrap_comicvine_provider_for_ui_cache

logger = structlog.get_logger(__name__)

router = APIRouter()
issue_router = APIRouter()

_GetTemplates = Callable[[], Jinja2Templates]
_BuildContext = Callable[..., dict[str, object]]

_get_templates: _GetTemplates | None = None
_build_context: _BuildContext | None = None


def configure_series_detail_routes(
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
        msg = "series detail routes have not been configured with templates"
        raise RuntimeError(msg)
    return _get_templates()


def _ctx(request: Request, user: object | None = None, **kwargs: object) -> dict[str, object]:
    if _build_context is None:
        msg = "series detail routes have not been configured with a context builder"
        raise RuntimeError(msg)
    context: Mapping[str, object] = _build_context(request, user, **kwargs)
    return dict(context)


async def load_series_issues_context(
    session: DbSession,
    series_id: int,
    issue_status: str | None,
    page: int,
    sort: str = "-issue_number",
) -> dict[str, object]:
    """Load issue stats and paginated issues for a series."""
    count_result = await session.execute(
        select(Issue.status, func.count(Issue.id))
        .where(Issue.series_id == series_id)
        .group_by(Issue.status)
    )
    status_counts: dict[str, int] = {str(row[0]): row[1] for row in count_result.all()}
    owned_count = status_counts.get(IssueStatus.OWNED, 0)
    wanted_count = status_counts.get(IssueStatus.WANTED, 0)
    downloading_count = status_counts.get(IssueStatus.DOWNLOADING, 0)
    total_issue_count = sum(status_counts.values())

    per_page = 50
    issue_filters = [Issue.series_id == series_id]
    if issue_status:
        issue_filters.append(Issue.status == issue_status)

    filtered_total: int = (
        await session.execute(select(func.count(Issue.id)).where(*issue_filters))
    ).scalar_one()
    total_pages = max(1, (filtered_total + per_page - 1) // per_page)
    page = min(page, total_pages)
    offset = (page - 1) * per_page

    if sort.startswith("-"):
        sort_field = sort[1:]
        sort_desc = True
    else:
        sort_field = sort
        sort_desc = False

    sort_column = {
        "issue_number": Issue.issue_number,
        "title": Issue.title,
        "release_date": Issue.release_date,
        "status": Issue.status,
    }.get(sort_field, Issue.issue_number)

    order_clause = sort_column.desc().nullslast() if sort_desc else sort_column.asc().nullslast()

    issues_result = await session.execute(
        select(Issue).where(*issue_filters).order_by(order_clause).limit(per_page).offset(offset)
    )
    issues = list(issues_result.scalars().all())

    return {
        "issues": issues,
        "owned_count": owned_count,
        "wanted_count": wanted_count,
        "downloading_count": downloading_count,
        "total_issue_count": total_issue_count,
        "filtered_total": filtered_total,
        "page": page,
        "total_pages": total_pages,
        "issue_status": issue_status or "",
        "issue_sort": sort,
    }


@router.get("/series/{series_id}", response_class=HTMLResponse, include_in_schema=False)
async def series_detail(
    request: Request,
    series_id: int,
    user: AuthenticatedUser,
    session: DbSession,
    issue_status: str | None = Query(None),
    page: int = Query(1, ge=1),
    issue_sort: str = Query("-issue_number"),
    source: Annotated[str | None, Query(alias="from")] = None,
) -> Response:
    """Render the series detail page with issues."""
    result = await session.execute(
        select(Series)
        .options(
            joinedload(Series.publisher),
            joinedload(Series.parent_series),
            joinedload(Series.child_series),
        )
        .where(Series.id == series_id)
    )
    series = result.unique().scalar_one_or_none()
    if series is None:
        return RedirectResponse(url="/series", status_code=302)

    issues_ctx = await load_series_issues_context(
        session, series_id, issue_status, page, sort=issue_sort
    )

    file_count: int = (
        await session.execute(
            select(func.count(LibraryFile.id)).where(
                LibraryFile.issue_id.in_(select(Issue.id).where(Issue.series_id == series_id))
            )
        )
    ).scalar_one()
    delete_context = await SeriesService.build_delete_context(session, [series_id])

    return _templates().TemplateResponse(
        request,
        "pages/series_detail.html",
        _ctx(
            request,
            user,
            series=series,
            file_count=file_count,
            delete_file_count=delete_context.linked_file_count,
            detail_origin=source if source == "pull-list" else None,
            **issues_ctx,
        ),
    )


@issue_router.get("/issues/{issue_id}", response_class=HTMLResponse, include_in_schema=False)
async def issue_detail(
    request: Request,
    issue_id: int,
    user: AuthenticatedUser,
    session: DbSession,
) -> Response:
    """Render the issue detail page, fetching metadata on-demand if missing."""
    result = await session.execute(
        select(Issue)
        .options(
            joinedload(Issue.series).joinedload(Series.publisher),
            joinedload(Issue.library_file),
            joinedload(Issue.creators),
        )
        .where(Issue.id == issue_id)
    )
    issue = result.unique().scalar_one_or_none()
    if issue is None:
        return RedirectResponse(url="/series", status_code=302)

    # On-demand metadata enrichment: fetch description from ComicVine if missing.
    if issue.comicvine_id and not issue.description:
        try:
            from pullbox.core.comicvine_key import get_comicvine_api_key
            from pullbox.providers.metadata.comicvine import ComicVineError, ComicVineProvider

            api_key = await get_comicvine_api_key(session)
            provider = ComicVineProvider(api_key=api_key)
            provider = wrap_comicvine_provider_for_ui_cache(provider, request)
            meta = await provider.get_issue(str(issue.comicvine_id))

            if meta.description and not issue.description:
                issue.description = meta.description
            if meta.comicvine_url and not issue.comicvine_url:
                issue.comicvine_url = meta.comicvine_url
            if meta.store_date:
                from pullbox.services.metadata_service import _parse_date

                parsed = _parse_date(meta.store_date)
                if parsed and not issue.store_date:
                    issue.store_date = parsed
            if meta.cover_url and not issue.cover_url:
                issue.cover_url = meta.cover_url

            issue.metadata_source = "comicvine"
            await session.flush()
            logger.info(
                "issue_metadata_enriched",
                issue_id=issue.id,
                comicvine_id=issue.comicvine_id,
            )
        except (ComicVineError, Exception):
            logger.exception("issue_metadata_enrich_failed", issue_id=issue.id)

    return _templates().TemplateResponse(
        request,
        "pages/issue_detail.html",
        _ctx(request, user, issue=issue),
    )


@issue_router.post(
    "/htmx/issues/{issue_id}/toggle",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def htmx_toggle_issue_status(
    request: Request,
    issue_id: int,
    user: AuthenticatedUser,
    session: DbSession,
) -> Response:
    """Toggle issue status between wanted and skipped (HTMX partial)."""
    result = await session.execute(
        select(Issue).options(joinedload(Issue.series)).where(Issue.id == issue_id)
    )
    issue = result.scalar_one_or_none()
    if issue is None:
        return Response(status_code=404)

    if issue.status == IssueStatus.WANTED:
        issue.status = IssueStatus.SKIPPED
        issue.manual_skip = True
    elif issue.status == IssueStatus.SKIPPED:
        issue.status = IssueStatus.WANTED
        issue.manual_skip = False

    await session.commit()

    return _templates().TemplateResponse(
        request,
        "partials/issue_row.html",
        _ctx(request, user, issue=issue, series=issue.series),
    )


@issue_router.get(
    "/htmx/issues/{issue_id}/search-results",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def htmx_issue_search_results(
    request: Request,
    issue_id: int,
    user: AuthenticatedUser,
    session: DbSession,
) -> Response:
    """Return interactive search results as an HTML partial (HTMX)."""
    from pullbox.api.v1.issues import _build_issue_search_log, _run_issue_search

    issue = await session.get(Issue, issue_id)
    if issue is None:
        return Response(status_code=404)

    bundle = await _run_issue_search(
        session,
        issue_id,
        include_download_clients=False,
    )
    issue_ctx = {"id": bundle.issue.id, "series_id": bundle.target.series_id}

    if bundle.runtime is None:
        return _templates().TemplateResponse(
            request,
            "partials/issue_search_results.html",
            _ctx(
                request,
                user,
                issue=issue_ctx,
                matched=[],
                rejected=[],
                search_time_ms=bundle.search_time_ms,
            ),
        )

    search_log = _build_issue_search_log(bundle)
    session.add(search_log)
    await session.commit()

    logger.info(
        "htmx_issue_search_results",
        issue_id=issue_id,
        matched=len(bundle.matched_items),
        rejected=len(bundle.rejected_items),
        search_time_ms=bundle.search_time_ms,
    )

    return _templates().TemplateResponse(
        request,
        "partials/issue_search_results.html",
        _ctx(
            request,
            user,
            issue=issue_ctx,
            matched=[m.model_dump() for m in bundle.matched_items],
            rejected=[r.model_dump() for r in bundle.rejected_items],
            search_time_ms=bundle.search_time_ms,
            search_log_id=search_log.id,
        ),
    )


@issue_router.post("/htmx/series/{series_id}/delete", include_in_schema=False)
async def htmx_delete_series(
    request: Request,
    series_id: int,
    user: AuthenticatedUser,
    session: DbSession,
) -> Response:
    """Delete a series, optionally removing files and/or folder from disk."""
    del user
    body = await request.json()
    delete_files: bool = body.get("delete_files", False)
    delete_folder: bool = body.get("delete_folder", False)

    from pullbox.core.exceptions import NotFoundError
    from pullbox.services.series_service import SeriesService

    try:
        await SeriesService.delete(
            session,
            series_id,
            delete_files=delete_files,
            delete_folder=delete_folder,
        )
        await session.flush()
    except NotFoundError:
        pass

    return RedirectResponse(url="/series", status_code=302)


@issue_router.post("/htmx/series/{series_id}/alternate-names", include_in_schema=False)
async def htmx_add_alternate_name(
    request: Request,
    series_id: int,
    user: AuthenticatedUser,
    session: DbSession,
) -> Response:
    """Add an alternate name to a series."""
    form = await request.form()
    name = str(form.get("name", "")).strip()
    if not name:
        return Response(status_code=400)

    series = await session.get(Series, series_id)
    if series is None:
        return Response(status_code=404)

    current = list(series.alternate_names) if series.alternate_names else []
    if name not in current:
        current.append(name)
        series.alternate_names = current

    return _templates().TemplateResponse(
        request,
        "partials/series_detail_alternate_names_list.html",
        _ctx(request, user, series=series),
    )


@issue_router.delete("/htmx/series/{series_id}/alternate-names/{name}", include_in_schema=False)
async def htmx_remove_alternate_name(
    request: Request,
    series_id: int,
    name: str,
    user: AuthenticatedUser,
    session: DbSession,
) -> Response:
    """Remove an alternate name from a series."""
    decoded_name = unquote(name)

    series = await session.get(Series, series_id)
    if series is None:
        return Response(status_code=404)

    current = list(series.alternate_names) if series.alternate_names else []
    if decoded_name in current:
        current.remove(decoded_name)
        series.alternate_names = current

    return _templates().TemplateResponse(
        request,
        "partials/series_detail_alternate_names_list.html",
        _ctx(request, user, series=series),
    )


@issue_router.get(
    "/htmx/series/{series_id}/issues",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def htmx_series_issues(
    request: Request,
    series_id: int,
    user: AuthenticatedUser,
    session: DbSession,
    issue_status: str | None = Query(None),
    page: int = Query(1, ge=1),
    issue_sort: str = Query("-issue_number"),
) -> Response:
    """Return the series issues panel partial for HTMX polling."""
    series = await session.get(Series, series_id)
    if series is None:
        return Response(status_code=404)

    issues_ctx = await load_series_issues_context(
        session, series_id, issue_status, page, sort=issue_sort
    )

    return _templates().TemplateResponse(
        request,
        "partials/series_issues_bundle.html",
        _ctx(request, user, series=series, **issues_ctx),
    )
