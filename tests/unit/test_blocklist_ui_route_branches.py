"""Focused branch coverage for blocklist UI routes."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from pullbox.models.blocklist import BlocklistReason
from pullbox.services.blocklist_service import BlocklistService
from pullbox.ui import blocklist_routes


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
def configured_blocklist_routes(monkeypatch: pytest.MonkeyPatch) -> RecordingTemplates:
    templates = RecordingTemplates()
    monkeypatch.setattr(blocklist_routes, "_get_templates", lambda: templates)
    monkeypatch.setattr(
        blocklist_routes,
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
def test_blocklist_runtime_dependency_guards(
    monkeypatch: pytest.MonkeyPatch,
    attribute: str,
    callable_name: str,
    error: str,
) -> None:
    monkeypatch.setattr(blocklist_routes, attribute, None)
    callable_obj = getattr(blocklist_routes, callable_name)

    with pytest.raises(RuntimeError, match=error):
        if callable_name == "_ctx":
            callable_obj(SimpleNamespace())
        else:
            callable_obj()


def test_configure_blocklist_routes_sets_runtime_dependencies() -> None:
    templates = RecordingTemplates()
    originals = {
        "_get_templates": blocklist_routes._get_templates,
        "_build_context": blocklist_routes._build_context,
    }
    try:
        blocklist_routes.configure_blocklist_routes(
            get_templates=lambda: templates,
            build_context=lambda request, user=None, **kwargs: {
                "request": request,
                "user": user,
                **kwargs,
            },
        )

        assert blocklist_routes._templates() is templates
        assert blocklist_routes._ctx(SimpleNamespace(), marker=True)["marker"] is True
    finally:
        for name, value in originals.items():
            setattr(blocklist_routes, name, value)


def test_blocklist_normalizers_cover_default_invalid_and_valid_values() -> None:
    assert blocklist_routes.normalize_blocklist_sort(None) == "-created_at"
    assert blocklist_routes.normalize_blocklist_sort("title") == "title"
    assert blocklist_routes.normalize_blocklist_sort("-series") == "-series"
    assert blocklist_routes.normalize_blocklist_sort("bogus") == "-created_at"
    assert blocklist_routes.parse_blocklist_reason(None) == (None, "")
    assert blocklist_routes.parse_blocklist_reason("bogus") == (None, "")
    assert blocklist_routes.parse_blocklist_reason("failed") == (
        BlocklistReason.FAILED,
        "failed",
    )


@pytest.mark.asyncio
async def test_load_blocklist_context_requeries_when_requested_page_is_too_high(
    configured_blocklist_routes: RecordingTemplates,
    monkeypatch: pytest.MonkeyPatch,
    db_session,
) -> None:
    calls: list[dict[str, object]] = []

    async def _list_entries(_session: object, **kwargs: object) -> tuple[list[object], int]:
        calls.append(kwargs)
        return [SimpleNamespace(id=1, error_message="failed")], 26

    async def _count_entries_by_reason(
        _session: object, **kwargs: object
    ) -> dict[BlocklistReason, int]:
        assert kwargs == {"reason": BlocklistReason.FAILED, "search": "Batman"}
        return {
            BlocklistReason.FAILED: 3,
            BlocklistReason.REJECTED: 2,
            BlocklistReason.MANUAL: 1,
        }

    monkeypatch.setattr(BlocklistService, "list_entries", _list_entries)
    monkeypatch.setattr(BlocklistService, "count_entries_by_reason", _count_entries_by_reason)

    context = await blocklist_routes.load_blocklist_context(
        db_session,
        reason="failed",
        search="Batman",
        sort="bogus",
        page=99,
    )

    assert len(calls) == 2
    assert calls[0]["offset"] == 2450
    assert calls[1]["offset"] == 25
    assert context["total"] == 26
    assert context["page"] == 2
    assert context["total_pages"] == 2
    assert context["reason_filter"] == "failed"
    assert context["search_query"] == "Batman"
    assert context["sort"] == "-created_at"
    assert context["failed_count"] == 3
    assert context["rejected_count"] == 2
    assert context["manual_count"] == 1


@pytest.mark.asyncio
async def test_blocklist_routes_select_templates_and_error_detail(
    configured_blocklist_routes: RecordingTemplates,
    monkeypatch: pytest.MonkeyPatch,
    db_session,
    route_request: SimpleNamespace,
) -> None:
    context = {
        "entries": [SimpleNamespace(id=42, error_message="blocked")],
        "total": 1,
        "page": 1,
        "total_pages": 1,
        "reason_filter": "",
        "search_query": "",
        "sort": "-created_at",
        "failed_count": 1,
        "rejected_count": 0,
        "manual_count": 0,
    }
    captured: list[dict[str, object]] = []

    async def _context(_session: object, **kwargs: object) -> dict[str, object]:
        captured.append(kwargs)
        return context

    async def _get_entry(_session: object, entry_id: int) -> object | None:
        if entry_id == 42:
            return SimpleNamespace(id=42, error_message="blocked")
        if entry_id == 43:
            return SimpleNamespace(id=43, error_message="")
        return None

    monkeypatch.setattr(blocklist_routes, "load_blocklist_context", _context)
    monkeypatch.setattr(BlocklistService, "get_entry", _get_entry)

    full = await blocklist_routes.blocklist_page(
        route_request,
        user=SimpleNamespace(username="admin"),
        session=db_session,
        reason=None,
        search=None,
        sort="-created_at",
        page=1,
    )
    hx = await blocklist_routes.blocklist_page(
        SimpleNamespace(headers={"HX-Request": "true"}, cookies={}, state=SimpleNamespace()),
        user=SimpleNamespace(username="admin"),
        session=db_session,
        reason="failed",
        search="Batman",
        sort="title",
        page=2,
    )
    body = await blocklist_routes.htmx_blocklist(
        route_request,
        user=SimpleNamespace(username="admin"),
        session=db_session,
        reason="rejected",
        search="Superman",
        sort="reason",
        page=3,
    )
    detail = await blocklist_routes.htmx_blocklist_error_detail(
        route_request,
        entry_id=42,
        user=SimpleNamespace(username="admin"),
        session=db_session,
    )

    assert full.template_name == "pages/blocklist.html"
    assert hx.template_name == "partials/blocklist_content_bundle.html"
    assert body.template_name == "partials/blocklist_results_body.html"
    assert detail.template_name == "partials/blocklist_error_detail.html"
    assert detail.context["entry"].id == 42
    assert captured[1]["reason"] == "failed"
    assert captured[2]["page"] == 3

    for entry_id in (43, 999):
        with pytest.raises(HTTPException) as exc:
            await blocklist_routes.htmx_blocklist_error_detail(
                route_request,
                entry_id=entry_id,
                user=SimpleNamespace(username="admin"),
                session=db_session,
            )
        assert exc.value.status_code == 404
