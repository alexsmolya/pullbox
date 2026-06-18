"""Focused branch coverage for search history UI routes."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from pullbox.models.issue import Issue
from pullbox.models.search_log import SearchLog, SearchType
from pullbox.models.series import Series
from pullbox.ui import search_history_routes


class RecordingTemplates:
    """Tiny templates stand-in that records route renders."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def TemplateResponse(  # noqa: N802 - mirrors Starlette's template API.
        self,
        _request: object,
        template_name: str,
        context: dict[str, object],
    ) -> SimpleNamespace:
        response = SimpleNamespace(template_name=template_name, context=context, status_code=200)
        self.calls.append((template_name, context))
        return response


@pytest.fixture
def configured_search_history_routes(monkeypatch: pytest.MonkeyPatch) -> RecordingTemplates:
    templates = RecordingTemplates()
    monkeypatch.setattr(search_history_routes, "_get_templates", lambda: templates)
    monkeypatch.setattr(
        search_history_routes,
        "_build_context",
        lambda request, user=None, **kwargs: {"request": request, "user": user, **kwargs},
    )
    return templates


@pytest.fixture
def route_request() -> SimpleNamespace:
    return SimpleNamespace(headers={}, cookies={}, state=SimpleNamespace())


async def _seed_search_issue(db_session) -> Issue:
    series = Series(title="Batman", sort_title="batman")
    db_session.add(series)
    await db_session.flush()
    issue = Issue(series_id=series.id, issue_number=1)
    db_session.add(issue)
    await db_session.flush()
    return issue


@pytest.mark.parametrize(
    ("attribute", "callable_name", "error"),
    [
        ("_get_templates", "_templates", "templates"),
        ("_build_context", "_ctx", "context builder"),
    ],
)
def test_search_history_runtime_dependency_guards(
    monkeypatch: pytest.MonkeyPatch,
    attribute: str,
    callable_name: str,
    error: str,
) -> None:
    monkeypatch.setattr(search_history_routes, attribute, None)
    callable_obj = getattr(search_history_routes, callable_name)

    with pytest.raises(RuntimeError, match=error):
        if callable_name == "_ctx":
            callable_obj(SimpleNamespace())
        else:
            callable_obj()


def test_configure_search_history_routes_sets_runtime_dependencies() -> None:
    templates = RecordingTemplates()
    originals = {
        "_get_templates": search_history_routes._get_templates,
        "_build_context": search_history_routes._build_context,
    }
    try:
        search_history_routes.configure_search_history_routes(
            get_templates=lambda: templates,
            build_context=lambda request, user=None, **kwargs: {
                "request": request,
                "user": user,
                **kwargs,
            },
        )

        assert search_history_routes._templates() is templates
        assert search_history_routes._ctx(SimpleNamespace(), marker=True)["marker"] is True
    finally:
        for name, value in originals.items():
            setattr(search_history_routes, name, value)


@pytest.mark.asyncio
async def test_load_search_history_context_filters_none_confidence_and_refresh_url(
    configured_search_history_routes: RecordingTemplates,
    db_session,
) -> None:
    issue = await _seed_search_issue(db_session)
    db_session.add_all(
        [
            SearchLog(
                issue_id=issue.id,
                series_title="Batman",
                issue_number=idx,
                search_type=SearchType.MANUAL,
                results_found=idx,
                results_grabbed=1,
                results_queued=2,
                results_rejected=3,
                best_confidence=None,
                details={"run_state": "running"} if idx == 26 else {},
            )
            for idx in range(1, 27)
        ]
    )
    db_session.add(
        SearchLog(
            issue_id=issue.id,
            series_title="Superman",
            issue_number=1,
            search_type=SearchType.AUTOMATED,
            results_found=5,
            best_confidence="high",
        )
    )
    await db_session.commit()

    context = await search_history_routes.load_search_history_context(
        db_session,
        search_type_filter=" manual ",
        confidence_filter=" NONE ",
        search_query=" Batman ",
        sort="series_title",
        requested_page=2,
    )

    assert context["search_log_total"] == 26
    assert context["search_log_pages"] == 2
    assert context["page"] == 2
    assert context["search_log_grabbed_total"] == 26
    assert context["search_log_queued_total"] == 52
    assert context["search_log_rejected_total"] == 78
    assert context["search_type_filter"] == "manual"
    assert context["confidence_filter"] == "none"
    assert context["search_query"] == "Batman"
    assert context["sort"] == "series_title"
    assert context["search_history_refresh_url"] == (
        "/search-history?search_type=manual&confidence=none&search=Batman&sort=series_title&page=2"
    )


@pytest.mark.asyncio
async def test_load_search_history_context_filters_explicit_confidence(
    configured_search_history_routes: RecordingTemplates,
    db_session,
) -> None:
    issue = await _seed_search_issue(db_session)
    db_session.add_all(
        [
            SearchLog(
                issue_id=issue.id,
                series_title="Batman",
                issue_number=1,
                search_type=SearchType.MANUAL,
                results_found=5,
                best_confidence="high",
                details={"run_state": "running"},
            ),
            SearchLog(
                issue_id=issue.id,
                series_title="Batman",
                issue_number=2,
                search_type=SearchType.MANUAL,
                results_found=1,
                best_confidence="low",
            ),
        ]
    )
    await db_session.commit()

    context = await search_history_routes.load_search_history_context(
        db_session,
        search_type_filter=None,
        confidence_filter="high",
        search_query=None,
        sort="-created_at",
        requested_page=1,
    )

    assert context["search_log_total"] == 1
    assert context["search_logs"][0].best_confidence == "high"
    assert context["search_history_has_active_logs"] is True
    assert context["search_history_refresh_url"] == "/search-history?confidence=high"


@pytest.mark.asyncio
async def test_search_history_page_selects_full_and_hx_templates(
    configured_search_history_routes: RecordingTemplates,
    monkeypatch: pytest.MonkeyPatch,
    db_session,
    route_request: SimpleNamespace,
) -> None:
    captured: list[dict[str, object]] = []

    async def _context(_session: object, **kwargs: object) -> dict[str, object]:
        captured.append(kwargs)
        return {"search_logs": [], "search_log_total": 0}

    monkeypatch.setattr(search_history_routes, "load_search_history_context", _context)

    full = await search_history_routes.search_history_page(
        route_request,
        user=SimpleNamespace(username="admin"),
        session=db_session,
        search_type_filter=None,
        confidence_filter=None,
        search_query=None,
        sort="-created_at",
        page=1,
    )
    hx = await search_history_routes.search_history_page(
        SimpleNamespace(headers={"HX-Request": "true"}, cookies={}, state=SimpleNamespace()),
        user=SimpleNamespace(username="admin"),
        session=db_session,
        search_type_filter="manual",
        confidence_filter="high",
        search_query="Batman",
        sort="series_title",
        page=2,
    )

    assert full.template_name == "pages/search_history.html"
    assert hx.template_name == "partials/search_history_content_bundle.html"
    assert captured[1] == {
        "search_type_filter": "manual",
        "confidence_filter": "high",
        "search_query": "Batman",
        "sort": "series_title",
        "requested_page": 2,
    }


@pytest.mark.asyncio
async def test_search_history_log_detail_success_and_missing(
    configured_search_history_routes: RecordingTemplates,
    db_session,
    route_request: SimpleNamespace,
) -> None:
    issue = await _seed_search_issue(db_session)
    log = SearchLog(
        issue_id=issue.id,
        series_title="Batman",
        issue_number=1,
        search_type=SearchType.MANUAL,
        results_found=1,
    )
    db_session.add(log)
    await db_session.commit()
    await db_session.refresh(log)

    response = await search_history_routes.search_history_log_detail(
        route_request,
        log_id=log.id,
        user=SimpleNamespace(username="admin"),
        session=db_session,
    )

    assert response.template_name == "partials/search_history_log_detail.html"
    assert response.context["log"].id == log.id

    with pytest.raises(HTTPException) as exc:
        await search_history_routes.search_history_log_detail(
            route_request,
            log_id=999_999,
            user=SimpleNamespace(username="admin"),
            session=db_session,
        )
    assert exc.value.status_code == 404
