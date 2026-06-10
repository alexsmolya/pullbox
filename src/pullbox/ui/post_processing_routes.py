"""Post-processing page and HTMX UI routes."""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Protocol
from typing import cast as typing_cast

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import ColumnElement, String, and_, case, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from starlette.responses import Response

from pullbox.api.deps import AuthenticatedUser, DbSession
from pullbox.models.download import DownloadClientType, DownloadHistory, DownloadState
from pullbox.models.issue import Issue
from pullbox.models.series import Series
from pullbox.services.download_history_classification import (
    post_processing_failure_clause as shared_post_processing_failure_clause,
)
from pullbox.services.download_history_classification import (
    post_processing_history_clause,
    post_processing_success_clause,
)

router = APIRouter()

_POST_PROCESSING_HISTORY_PER_PAGE = 25
_POST_PROCESSING_RESULT_FILTERS = {"all", "imported", "failed"}
_POST_PROCESSING_FILTER_ALIASES = {"all", "active", "imported", "failed"}
_POST_PROCESSING_SORT_OPTIONS = {
    "title",
    "issue",
    "result",
    "client",
    "size",
    "completed_at",
}
_POST_PROCESSING_TABS = {"queue", "history"}


class _LoadPostProcessingLiveStatusMap(Protocol):
    def __call__(
        self,
        active_items: Sequence[DownloadHistory],
    ) -> Awaitable[dict[int, dict[str, object]]]: ...


_GetTemplates = Callable[[], Jinja2Templates]
_BuildContext = Callable[..., dict[str, object]]
_DownloadClientLabel = Callable[[str], str]
_GetRecentPostProcessingCompletionIds = Callable[[], set[int]]

_get_templates: _GetTemplates | None = None
_build_context: _BuildContext | None = None
_download_client_label: _DownloadClientLabel | None = None
_get_recent_completion_ids: _GetRecentPostProcessingCompletionIds | None = None
_load_live_status_map: _LoadPostProcessingLiveStatusMap | None = None
_sidebar_badge_no_store_headers: Mapping[str, str] = {}


def configure_post_processing_routes(
    *,
    get_templates: _GetTemplates,
    build_context: _BuildContext,
    download_client_label: _DownloadClientLabel,
    get_recent_completion_ids: _GetRecentPostProcessingCompletionIds,
    load_live_status_map: _LoadPostProcessingLiveStatusMap,
    sidebar_badge_no_store_headers: Mapping[str, str],
) -> None:
    """Provide shared UI runtime dependencies from the facade module."""
    global _get_templates
    global _build_context
    global _download_client_label
    global _get_recent_completion_ids
    global _load_live_status_map
    global _sidebar_badge_no_store_headers
    _get_templates = get_templates
    _build_context = build_context
    _download_client_label = download_client_label
    _get_recent_completion_ids = get_recent_completion_ids
    _load_live_status_map = load_live_status_map
    _sidebar_badge_no_store_headers = sidebar_badge_no_store_headers


def _templates() -> Jinja2Templates:
    if _get_templates is None:
        msg = "post-processing routes have not been configured with templates"
        raise RuntimeError(msg)
    return _get_templates()


def _ctx(request: Request, user: object | None = None, **kwargs: object) -> dict[str, object]:
    if _build_context is None:
        msg = "post-processing routes have not been configured with a context builder"
        raise RuntimeError(msg)
    context: Mapping[str, object] = _build_context(request, user, **kwargs)
    return dict(context)


def _client_label(client_type: str) -> str:
    if _download_client_label is None:
        msg = "post-processing routes have not been configured with a client labeler"
        raise RuntimeError(msg)
    return _download_client_label(client_type)


def _recent_completion_ids() -> set[int]:
    if _get_recent_completion_ids is None:
        msg = "post-processing routes have not been configured with completion tracking"
        raise RuntimeError(msg)
    return _get_recent_completion_ids()


async def _live_status_map(
    active_items: Sequence[DownloadHistory],
) -> dict[int, dict[str, object]]:
    if _load_live_status_map is None:
        msg = "post-processing routes have not been configured with live status loading"
        raise RuntimeError(msg)
    return await _load_live_status_map(active_items)


async def load_post_processing_client_options(
    session: AsyncSession,
    *,
    current_client: str | None,
) -> list[tuple[str, str]]:
    """Return client dropdown options for post-processing history."""
    result = await session.execute(
        select(DownloadHistory.download_client)
        .where(post_processing_history_clause())
        .distinct()
        .order_by(DownloadHistory.download_client)
    )
    options: list[tuple[str, str]] = [("", "All Clients")]
    seen_clients: set[str] = set()
    for client_value in result.scalars().all():
        normalized_value = (
            client_value.value
            if isinstance(client_value, DownloadClientType)
            else str(client_value)
        )
        if normalized_value in seen_clients:
            continue
        seen_clients.add(normalized_value)
        options.append((normalized_value, _client_label(normalized_value)))

    if current_client and current_client not in seen_clients:
        options.append((current_client, _client_label(current_client)))
    return options


def normalize_post_processing_result_filter(result_value: str | None) -> str:
    """Return a valid post-processing history result filter."""
    return result_value if result_value in _POST_PROCESSING_RESULT_FILTERS else "all"


def normalize_post_processing_tab(tab: str | None) -> str:
    """Return a valid post-processing page tab."""
    return tab if tab in _POST_PROCESSING_TABS else "queue"


def normalize_post_processing_filter_alias(filter_value: str | None) -> str:
    """Map legacy post-processing filter values onto the new result filter."""
    if filter_value not in _POST_PROCESSING_FILTER_ALIASES:
        return "all"
    if filter_value == "active":
        return "all"
    return normalize_post_processing_result_filter(filter_value)


def resolve_post_processing_result_filter(
    result_value: str | None,
    legacy_filter: str | None,
) -> str:
    """Resolve canonical and legacy query params into a current result filter."""
    if result_value is not None:
        return normalize_post_processing_result_filter(result_value)
    return normalize_post_processing_filter_alias(legacy_filter)


def normalize_post_processing_sort(sort: str | None) -> str:
    """Return a valid post-processing history sort key."""
    if not sort:
        return "-completed_at"

    sort_field = sort[1:] if sort.startswith("-") else sort
    if sort_field not in _POST_PROCESSING_SORT_OPTIONS:
        return "-completed_at"
    return sort


def post_processing_history_completed_expr() -> ColumnElement[datetime]:
    """Return the effective timestamp for post-processing history ordering."""
    return func.coalesce(
        DownloadHistory.imported_at,
        DownloadHistory.completed_at,
        DownloadHistory.updated_at,
    )


def get_post_processing_history_order_by(sort: str) -> list[ColumnElement[object]]:
    """Build ORDER BY clauses for post-processing history."""
    normalized_sort = normalize_post_processing_sort(sort)
    sort_desc = normalized_sort.startswith("-")
    sort_field = normalized_sort[1:] if sort_desc else normalized_sort

    result_sort = case(
        (DownloadHistory.imported_at.is_not(None), 0),
        (DownloadHistory.state == DownloadState.FAILED, 1),
        else_=2,
    )
    completed_expr = post_processing_history_completed_expr()

    sort_map: dict[str, list[object]] = {
        "title": [DownloadHistory.title],
        "issue": [Series.sort_title, Issue.issue_number],
        "result": [result_sort, completed_expr],
        "client": [DownloadHistory.download_client, completed_expr],
        "size": [DownloadHistory.file_size],
        "completed_at": [completed_expr],
    }
    sort_columns = sort_map.get(sort_field, [completed_expr])

    order_by: list[ColumnElement[object]] = []
    for col in sort_columns:
        column: ColumnElement[object] = col  # type: ignore[assignment]
        order_by.append(column.desc().nullslast() if sort_desc else column.asc().nullslast())
    order_by.append(DownloadHistory.id.desc())  # type: ignore[arg-type]
    return order_by


def post_processing_active_clause() -> ColumnElement[bool]:
    """Match downloads actively being post-processed."""
    return or_(
        DownloadHistory.state == DownloadState.POST_PROCESSING,
        and_(
            DownloadHistory.state == DownloadState.COMPLETED,
            DownloadHistory.imported_at.is_(None),
            DownloadHistory.downloaded_path.is_not(None),
        ),
    )


def get_recent_post_processing_completion_ids() -> set[int]:
    """Return IDs that should linger briefly in the queue after import completes."""
    from pullbox.tasks.download_task import get_all_post_processing_progress

    return {
        download_id
        for download_id, snapshot in get_all_post_processing_progress().items()
        if snapshot.state_tone == "success"
    }


def post_processing_imported_clause() -> ColumnElement[bool]:
    """Match downloads successfully imported into the library."""
    return post_processing_success_clause()


def post_processing_failed_clause() -> ColumnElement[bool]:
    """Match failed post-processing runs, excluding user-cancelled downloads."""
    return shared_post_processing_failure_clause()


async def load_post_processing_status_context(session: AsyncSession) -> dict[str, object]:
    """Load live status counts and active processing items for the post-processing page."""
    active_result = await session.execute(
        select(DownloadHistory)
        .options(joinedload(DownloadHistory.issue).joinedload(Issue.series))
        .where(post_processing_active_clause())
        .order_by(DownloadHistory.updated_at.desc())
    )
    active_items = list(active_result.unique().scalars().all())
    active_item_ids = {item.id for item in active_items}
    recent_completion_ids = _recent_completion_ids() - active_item_ids
    recent_imported_items: list[DownloadHistory] = []
    if recent_completion_ids:
        recent_result = await session.execute(
            select(DownloadHistory)
            .options(joinedload(DownloadHistory.issue).joinedload(Issue.series))
            .where(DownloadHistory.id.in_(recent_completion_ids))
            .order_by(
                DownloadHistory.imported_at.desc().nullslast(),
                DownloadHistory.updated_at.desc(),
            )
        )
        recent_imported_items = list(recent_result.unique().scalars().all())

    live_status_map = await _live_status_map(active_items)
    active_items.sort(
        key=lambda item: (
            0 if item.id in live_status_map else 1,
            -(item.updated_at.timestamp() if item.updated_at else 0),
        )
    )

    imported_clause = post_processing_imported_clause()
    if recent_completion_ids:
        imported_clause = and_(imported_clause, DownloadHistory.id.not_in(recent_completion_ids))

    imported_count: int = (
        await session.execute(select(func.count(DownloadHistory.id)).where(imported_clause))
    ).scalar_one()
    failed_count: int = (
        await session.execute(
            select(func.count(DownloadHistory.id)).where(post_processing_failed_clause())
        )
    ).scalar_one()
    active_count = len(active_items)
    recent_imported_count = len(recent_imported_items)

    return {
        "active_items": active_items,
        "recent_imported_items": recent_imported_items,
        "live_status_map": live_status_map,
        "active_count": active_count,
        "recent_imported_count": recent_imported_count,
        "imported_count": imported_count,
        "failed_count": failed_count,
        "total_count": active_count + recent_imported_count + imported_count + failed_count,
    }


async def load_post_processing_live_status_map(
    active_items: Sequence[DownloadHistory],
) -> dict[int, dict[str, object]]:
    """Return live post-processing UI status for actively processing downloads."""
    from pullbox.tasks.download_task import PostProcessingPhase, get_all_post_processing_progress

    phase_progress_map: dict[PostProcessingPhase, tuple[float, str]] = {
        PostProcessingPhase.RESOLVING_SOURCE: (18.0, "Step 1 of 5"),
        PostProcessingPhase.VALIDATING_FILES: (36.0, "Step 2 of 5"),
        PostProcessingPhase.PREPARING_DESTINATION: (54.0, "Step 3 of 5"),
        PostProcessingPhase.REGISTERING_LIBRARY_FILE: (92.0, "Step 5 of 5"),
        PostProcessingPhase.IMPORT_COMPLETE: (100.0, "Complete"),
    }

    snapshots = get_all_post_processing_progress()
    now_epoch = datetime.now(UTC).timestamp()
    live_status_map: dict[int, dict[str, object]] = {}

    for item in active_items:
        snapshot = snapshots.get(item.id)
        if snapshot is None:
            continue
        transfer_progress_pct: float | None = None
        phase_progress_pct: float | None = None
        phase_progress_label: str | None = None
        if not snapshot.phase.shows_transfer_metrics:
            phase_progress_pct, phase_progress_label = phase_progress_map.get(
                snapshot.phase,
                (0.0, "Pending"),
            )
        if (
            snapshot.transfer_total_bytes
            and snapshot.transfer_done_bytes is not None
            and snapshot.transfer_total_bytes > 0
        ):
            transfer_progress_pct = round(
                min(
                    max(
                        (snapshot.transfer_done_bytes / snapshot.transfer_total_bytes) * 100,
                        0.0,
                    ),
                    100.0,
                ),
                1,
            )
        live_status_map[item.id] = {
            "phase_label": snapshot.phase_label,
            "status_label": snapshot.phase.status_label,
            "shows_transfer_metrics": snapshot.phase.shows_transfer_metrics,
            "elapsed_seconds": max(0, int(now_epoch - snapshot.started_at_epoch)),
            "state_tone": snapshot.state_tone,
            "phase_progress_pct": phase_progress_pct,
            "phase_progress_label": phase_progress_label,
            "transfer_progress_pct": transfer_progress_pct,
            "transfer_done_bytes": snapshot.transfer_done_bytes,
            "transfer_total_bytes": snapshot.transfer_total_bytes,
            "transfer_speed_bytes": snapshot.transfer_speed_bytes,
            "transfer_eta_seconds": snapshot.transfer_eta_seconds,
        }

    return live_status_map


async def load_post_processing_history_context(
    session: AsyncSession,
    *,
    result_value: str,
    client_value: str | None,
    search_query: str,
    page: int,
    sort: str,
) -> dict[str, object]:
    """Load the filtered post-processing history panel context."""
    normalized_result = normalize_post_processing_result_filter(result_value)
    normalized_sort = normalize_post_processing_sort(sort)
    trimmed_search = search_query.strip()
    trimmed_client = client_value.strip() if client_value else ""
    imported_clause = post_processing_imported_clause()
    recent_completion_ids = _recent_completion_ids()
    if recent_completion_ids:
        imported_clause = and_(imported_clause, DownloadHistory.id.not_in(recent_completion_ids))
    failed_clause = post_processing_failed_clause()
    history_filters: list[ColumnElement[bool]] = [or_(imported_clause, failed_clause)]
    if normalized_result == "imported":
        history_filters.append(imported_clause)
    elif normalized_result == "failed":
        history_filters.append(failed_clause)

    if trimmed_client:
        history_filters.append(DownloadHistory.download_client == trimmed_client)

    if trimmed_search:
        search_term = f"%{trimmed_search}%"
        history_filters.append(
            or_(
                DownloadHistory.title.ilike(search_term),
                Series.title.ilike(search_term),
                cast(Issue.issue_number, String).ilike(search_term),
            )
        )

    history_total: int = (
        await session.execute(
            select(func.count(DownloadHistory.id))
            .select_from(DownloadHistory)
            .join(Issue, DownloadHistory.issue_id == Issue.id)
            .join(Series, Issue.series_id == Series.id)
            .where(*history_filters)
        )
    ).scalar_one()

    history_imported_count, history_failed_count = (
        await session.execute(
            select(
                func.coalesce(func.sum(case((imported_clause, 1), else_=0)), 0),
                func.coalesce(func.sum(case((failed_clause, 1), else_=0)), 0),
            )
            .select_from(DownloadHistory)
            .join(Issue, DownloadHistory.issue_id == Issue.id)
            .join(Series, Issue.series_id == Series.id)
            .where(*history_filters)
        )
    ).one()

    total_pages = max(
        1,
        (history_total + _POST_PROCESSING_HISTORY_PER_PAGE - 1)
        // _POST_PROCESSING_HISTORY_PER_PAGE,
    )
    page = min(page, total_pages)
    offset = (page - 1) * _POST_PROCESSING_HISTORY_PER_PAGE

    history_result = await session.execute(
        select(DownloadHistory)
        .join(Issue, DownloadHistory.issue_id == Issue.id)
        .join(Series, Issue.series_id == Series.id)
        .options(joinedload(DownloadHistory.issue).joinedload(Issue.series))
        .where(*history_filters)
        .order_by(*get_post_processing_history_order_by(normalized_sort))
        .limit(_POST_PROCESSING_HISTORY_PER_PAGE)
        .offset(offset)
    )
    history_items = list(history_result.unique().scalars().all())
    client_options = await load_post_processing_client_options(
        session,
        current_client=trimmed_client or None,
    )

    return {
        "history_items": history_items,
        "history_total": history_total,
        "history_imported_count": int(history_imported_count or 0),
        "history_failed_count": int(history_failed_count or 0),
        "page": page,
        "total_pages": total_pages,
        "result_filter": normalized_result,
        "client_filter": trimmed_client,
        "client_options": client_options,
        "search_query": trimmed_search,
        "sort": normalized_sort,
    }


@router.get("/post-processing", response_class=HTMLResponse, include_in_schema=False)
async def post_processing(
    request: Request,
    user: AuthenticatedUser,
    session: DbSession,
    tab: str = Query("queue"),
    result: str | None = Query(None),
    filter: str | None = Query(None, alias="filter"),
    client: str | None = Query(None),
    search: str = Query(""),
    sort: str = Query("-completed_at"),
    page: int = Query(1, ge=1),
) -> Response:
    """Render the post-processing page showing file processing status."""
    normalized_tab = normalize_post_processing_tab(tab)
    result_filter = resolve_post_processing_result_filter(result, filter)
    status_ctx = await load_post_processing_status_context(session)
    history_ctx = await load_post_processing_history_context(
        session,
        result_value=result_filter,
        client_value=client,
        search_query=search,
        page=page,
        sort=sort,
    )

    ctx = _ctx(
        request,
        user,
        tab=normalized_tab,
        download_client_label=_client_label,
        **status_ctx,
        **history_ctx,
    )

    if request.headers.get("HX-Request"):
        if normalized_tab == "history" and request.headers.get("HX-Target") == "pp-history-results":
            return _templates().TemplateResponse(
                request, "partials/pp_history_results_bundle.html", ctx
            )
        return _templates().TemplateResponse(request, "partials/pp_content_bundle.html", ctx)

    return _templates().TemplateResponse(request, "pages/post_processing.html", ctx)


@router.get("/htmx/post-processing/queue", response_class=HTMLResponse, include_in_schema=False)
async def htmx_pp_queue(
    request: Request,
    user: AuthenticatedUser,
    session: DbSession,
) -> Response:
    """Return the post-processing queue partial for HTMX polling."""
    status_ctx = await load_post_processing_status_context(session)
    history_total = typing_cast("int", status_ctx["imported_count"]) + typing_cast(
        "int", status_ctx["failed_count"]
    )
    return _templates().TemplateResponse(
        request,
        "partials/pp_queue_bundle.html",
        _ctx(
            request,
            user,
            tab="queue",
            history_total=history_total,
            download_client_label=_client_label,
            **status_ctx,
        ),
        headers=_sidebar_badge_no_store_headers,
    )


@router.get(
    "/htmx/post-processing/queue/{download_id}/detail",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def htmx_pp_queue_detail(
    request: Request,
    download_id: int,
    user: AuthenticatedUser,
    session: DbSession,
) -> Response:
    """Return one active post-processing row's deferred detail cards."""
    result = await session.execute(
        select(DownloadHistory)
        .options(joinedload(DownloadHistory.issue).joinedload(Issue.series))
        .where(
            DownloadHistory.id == download_id,
            post_processing_active_clause(),
        )
    )
    dl = result.unique().scalar_one_or_none()
    if dl is None:
        raise HTTPException(status_code=404, detail="Post-processing queue item not found")

    live_status_map = await _live_status_map([dl])
    return _templates().TemplateResponse(
        request,
        "partials/pp_queue_detail.html",
        _ctx(
            request,
            user,
            dl=dl,
            live=live_status_map.get(dl.id),
            download_client_label=_client_label,
        ),
    )


@router.get("/htmx/post-processing/status", response_class=HTMLResponse, include_in_schema=False)
async def htmx_pp_status(
    request: Request,
    user: AuthenticatedUser,
    session: DbSession,
) -> Response:
    """Backward-compatible alias for the post-processing queue partial."""
    return await htmx_pp_queue(request, user, session)


@router.get("/htmx/post-processing/history", response_class=HTMLResponse, include_in_schema=False)
async def htmx_pp_history(
    request: Request,
    user: AuthenticatedUser,
    session: DbSession,
    result: str | None = Query(None),
    filter: str | None = Query(None, alias="filter"),
    client: str | None = Query(None),
    search: str = Query(""),
    sort: str = Query("-completed_at"),
    page: int = Query(1, ge=1),
) -> Response:
    """Return the post-processing history partial for HTMX polling."""
    result_filter = resolve_post_processing_result_filter(result, filter)
    status_ctx = await load_post_processing_status_context(session)
    history_ctx = await load_post_processing_history_context(
        session,
        result_value=result_filter,
        client_value=client,
        search_query=search,
        page=page,
        sort=sort,
    )
    return _templates().TemplateResponse(
        request,
        "partials/pp_history_results_bundle.html",
        _ctx(
            request,
            user,
            tab="history",
            download_client_label=_client_label,
            **status_ctx,
            **history_ctx,
        ),
    )
