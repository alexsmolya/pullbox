"""Focused branch coverage for matching queue UI routes."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from pullbox.models.issue import Issue
from pullbox.models.library import FileFormat, LibraryFile, LibraryRoot, MatchConfidence
from pullbox.models.series import Series
from pullbox.ui import matching_routes


class RecordingTemplates:
    """Tiny templates stand-in that records matching route renders."""

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
def configured_matching_routes(monkeypatch: pytest.MonkeyPatch) -> RecordingTemplates:
    templates = RecordingTemplates()
    monkeypatch.setattr(matching_routes, "_get_templates", lambda: templates)
    monkeypatch.setattr(
        matching_routes,
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
def test_matching_runtime_dependency_guards(
    monkeypatch: pytest.MonkeyPatch,
    attribute: str,
    callable_name: str,
    error: str,
) -> None:
    monkeypatch.setattr(matching_routes, attribute, None)
    callable_obj = getattr(matching_routes, callable_name)

    with pytest.raises(RuntimeError, match=error):
        if callable_name == "_ctx":
            callable_obj(SimpleNamespace())
        else:
            callable_obj()


def test_configure_matching_routes_sets_runtime_dependencies() -> None:
    templates = RecordingTemplates()
    originals = {
        "_get_templates": matching_routes._get_templates,
        "_build_context": matching_routes._build_context,
    }
    try:
        matching_routes.configure_matching_routes(
            get_templates=lambda: templates,
            build_context=lambda request, user=None, **kwargs: {
                "request": request,
                "user": user,
                **kwargs,
            },
        )

        assert matching_routes._templates() is templates
        assert matching_routes._ctx(SimpleNamespace(), marker=True)["marker"] is True
    finally:
        for name, value in originals.items():
            setattr(matching_routes, name, value)


@pytest.mark.asyncio
async def test_matching_queue_paginates_unmatched_files(
    configured_matching_routes: RecordingTemplates,
    db_session,
    route_request: SimpleNamespace,
) -> None:
    root = LibraryRoot(name="Main", path="/library", enabled=True)
    db_session.add(root)
    await db_session.flush()
    db_session.add_all(
        [
            LibraryFile(
                file_path=f"/library/unmatched-{idx}.cbz",
                file_name=f"unmatched-{idx}.cbz",
                file_size=idx,
                file_format=FileFormat.CBZ,
                file_modified_at=datetime(2026, 1, 1, tzinfo=UTC),
                match_confidence=MatchConfidence.UNMATCHED,
                library_root_id=root.id,
            )
            for idx in range(55)
        ]
    )
    await db_session.commit()

    response = await matching_routes.matching_queue(
        route_request,
        user=SimpleNamespace(username="admin"),
        session=db_session,
        page=99,
    )

    assert response.template_name == "pages/matching_queue.html"
    assert response.context["total"] == 55
    assert response.context["page"] == 2
    assert response.context["total_pages"] == 2
    assert len(response.context["files"]) == 5


@pytest.mark.asyncio
async def test_matching_series_search_short_and_matching_queries(
    configured_matching_routes: RecordingTemplates,
    db_session,
    route_request: SimpleNamespace,
) -> None:
    db_session.add_all(
        [
            Series(title="Batman", sort_title="batman", year_start=2026),
            Series(title="Superman", sort_title="superman", year_start=2026),
        ]
    )
    await db_session.commit()

    short = await matching_routes.htmx_matching_series_search(
        route_request,
        user=SimpleNamespace(username="admin"),
        session=db_session,
        q=" b ",
    )
    found = await matching_routes.htmx_matching_series_search(
        route_request,
        user=SimpleNamespace(username="admin"),
        session=db_session,
        q=" Bat ",
    )

    assert short.template_name == "partials/matching_series_results.html"
    assert "series_list" not in short.context
    assert found.template_name == "partials/matching_series_results.html"
    assert [series.title for series in found.context["series_list"]] == ["Batman"]
    assert found.context["query"] == " Bat "


@pytest.mark.asyncio
async def test_matching_issues_lists_known_and_unknown_series(
    configured_matching_routes: RecordingTemplates,
    db_session,
    route_request: SimpleNamespace,
) -> None:
    series = Series(title="Batman", sort_title="batman", year_start=2026)
    db_session.add(series)
    await db_session.flush()
    db_session.add_all(
        [
            Issue(series_id=series.id, issue_number=2),
            Issue(series_id=series.id, issue_number=1),
        ]
    )
    await db_session.commit()

    known = await matching_routes.htmx_matching_issues(
        route_request,
        user=SimpleNamespace(username="admin"),
        session=db_session,
        series_id=series.id,
    )
    unknown = await matching_routes.htmx_matching_issues(
        route_request,
        user=SimpleNamespace(username="admin"),
        session=db_session,
        series_id=999_999,
    )

    assert known.template_name == "partials/matching_issues.html"
    assert known.context["series_title"] == "Batman"
    assert [issue.issue_number for issue in known.context["issues"]] == [1, 2]
    assert unknown.context["series_title"] == "Unknown"
    assert unknown.context["issues"] == []
