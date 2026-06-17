"""Focused branch coverage for pull-list UI routes."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from pullbox.models.issue import Issue, IssueStatus
from pullbox.models.series import Series
from pullbox.ui import pull_list_routes


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
def configured_pull_list_routes(monkeypatch: pytest.MonkeyPatch) -> RecordingTemplates:
    templates = RecordingTemplates()
    monkeypatch.setattr(pull_list_routes, "_get_templates", lambda: templates)
    monkeypatch.setattr(
        pull_list_routes,
        "_build_context",
        lambda request, user=None, **kwargs: {"request": request, "user": user, **kwargs},
    )
    return templates


@pytest.fixture
def route_request() -> SimpleNamespace:
    return SimpleNamespace(headers={}, cookies={}, state=SimpleNamespace())


@pytest.mark.parametrize(
    ("attribute", "callable_name", "error"),
    [
        ("_get_templates", "_templates", "templates"),
        ("_build_context", "_ctx", "context builder"),
    ],
)
def test_pull_list_runtime_dependency_guards(
    monkeypatch: pytest.MonkeyPatch,
    attribute: str,
    callable_name: str,
    error: str,
) -> None:
    monkeypatch.setattr(pull_list_routes, attribute, None)
    callable_obj = getattr(pull_list_routes, callable_name)

    with pytest.raises(RuntimeError, match=error):
        if callable_name == "_ctx":
            callable_obj(SimpleNamespace())
        else:
            callable_obj()


def test_configure_pull_list_routes_sets_runtime_dependencies() -> None:
    templates = RecordingTemplates()
    originals = {
        "_get_templates": pull_list_routes._get_templates,
        "_build_context": pull_list_routes._build_context,
    }
    try:
        pull_list_routes.configure_pull_list_routes(
            get_templates=lambda: templates,
            build_context=lambda request, user=None, **kwargs: {
                "request": request,
                "user": user,
                **kwargs,
            },
        )

        assert pull_list_routes._templates() is templates
        assert pull_list_routes._ctx(SimpleNamespace(), marker=True)["marker"] is True
    finally:
        for name, value in originals.items():
            setattr(pull_list_routes, name, value)


async def _seed_pull_list_data(db_session) -> None:
    wanted = Series(title="Batman", sort_title="batman", year_start=2026, monitored=True)
    complete = Series(title="Superman", sort_title="superman", year_start=2025, monitored=True)
    paused = Series(
        title="Wonder Woman", sort_title="wonder woman", year_start=2024, monitored=False
    )
    empty = Series(title="Empty", sort_title="empty", year_start=2023, monitored=True)
    db_session.add_all([wanted, complete, paused, empty])
    await db_session.flush()
    db_session.add_all(
        [
            Issue(series_id=wanted.id, issue_number=1, status=IssueStatus.OWNED),
            Issue(series_id=wanted.id, issue_number=2, status=IssueStatus.WANTED),
            Issue(series_id=wanted.id, issue_number=3, status=IssueStatus.DOWNLOADING),
            Issue(series_id=complete.id, issue_number=1, status=IssueStatus.OWNED),
            Issue(series_id=complete.id, issue_number=2, status=IssueStatus.OWNED),
            Issue(series_id=paused.id, issue_number=1, status=IssueStatus.WANTED),
        ]
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_pull_list_route_filters_sorts_metrics_and_templates(
    configured_pull_list_routes: RecordingTemplates,
    db_session,
    route_request: SimpleNamespace,
) -> None:
    await _seed_pull_list_data(db_session)

    wanted = await pull_list_routes.pull_list(
        route_request,
        user=SimpleNamespace(username="admin"),
        session=db_session,
        filter="wanted",
        search=" Batman ",
        sort="-progress",
        page=99,
    )
    complete_hx = await pull_list_routes.pull_list(
        SimpleNamespace(headers={"HX-Request": "true"}, cookies={}, state=SimpleNamespace()),
        user=SimpleNamespace(username="admin"),
        session=db_session,
        filter="complete",
        search=None,
        sort="-owned",
        page=1,
    )
    paused = await pull_list_routes.pull_list(
        route_request,
        user=SimpleNamespace(username="admin"),
        session=db_session,
        filter="paused",
        search="2024",
        sort="status",
        page=1,
    )
    fallback = await pull_list_routes.pull_list(
        route_request,
        user=SimpleNamespace(username="admin"),
        session=db_session,
        filter="bogus",
        search="",
        sort="bogus",
        page=1,
    )

    assert wanted.template_name == "pages/pull_list.html"
    assert wanted.context["filter_value"] == "wanted"
    assert wanted.context["search_query"] == "Batman"
    assert wanted.context["sort"] == "-progress"
    assert wanted.context["page"] == 1
    assert wanted.context["total"] == 1
    assert wanted.context["pull_data"][0]["series"].title == "Batman"
    assert wanted.context["pull_data"][0]["completion_pct"] == 33
    assert wanted.context["pull_metrics"] == {
        "monitored_series": 3,
        "paused_series": 1,
        "wanted_series": 1,
        "total_wanted": 1,
        "downloading_series": 1,
        "completion_pct": 60,
        "wanted_ratio": 0.2,
        "downloading_ratio": 0.25,
        "paused_ratio": 0.25,
    }
    assert complete_hx.template_name == "partials/pull_list_content_bundle.html"
    assert complete_hx.context["filter_value"] == "complete"
    assert complete_hx.context["pull_data"][0]["series"].title == "Superman"
    assert paused.context["filter_value"] == "paused"
    assert paused.context["pull_data"][0]["series"].title == "Wonder Woman"
    assert fallback.context["filter_value"] == ""
    assert fallback.context["sort"] == "title"
