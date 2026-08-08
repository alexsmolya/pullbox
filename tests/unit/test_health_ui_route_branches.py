"""Focused branch coverage for the split health UI route module."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from pullbox.ui import health_routes
from pullbox.ui.health_presenters import (
    HealthCheckItemView,
    HealthComponentView,
    HealthFooterStripView,
    HealthHistoryRowView,
    HealthMonitoringView,
)


class RecordingTemplates:
    """Tiny templates stand-in that records health route renders."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def TemplateResponse(  # noqa: N802 - mirrors Starlette's template API.
        self,
        _request: object,
        template_name: str,
        context: dict[str, object],
    ) -> SimpleNamespace:
        response = SimpleNamespace(
            template_name=template_name,
            context=context,
            headers={},
            status_code=200,
        )
        self.calls.append((template_name, context))
        return response


def _component(key: str = "database") -> HealthComponentView:
    return HealthComponentView(
        key=key,
        component_key=key,
        display_name=key.replace("_", " ").title(),
        detail_title=f"{key} detail",
        status="healthy",
        status_label="Healthy",
        pill_tone="pill-success",
        led_tone="green",
        card_tone="success",
        message="ok",
        sublabel="ready",
        stats=(),
        detail_stats=(),
        detail_variant="standard",
        checks=(),
        history=(),
        history_page=2,
        history_total_pages=3,
        history_total_count=12,
        history_sort="status",
        history_search_query="needle",
        subject_key=key,
        history_base_path=f"/health/{key}",
    )


def _health_view() -> HealthMonitoringView:
    return HealthMonitoringView(
        overall_status="healthy",
        total_monitors=1,
        total_checks=1,
        gauges=(),
        scoreboard=(),
        components=(
            _component("database"),
            _component("download_clients"),
            _component("indexers"),
        ),
        footer=HealthFooterStripView(
            total_monitors=1,
            total_checks=1,
            healthy_count=1,
            degraded_count=0,
            unhealthy_count=0,
        ),
    )


def _check_item() -> HealthCheckItemView:
    return HealthCheckItemView(
        key="database",
        name="Database",
        status="healthy",
        status_label="Healthy",
        pill_tone="pill-success",
        led_tone="green",
        message="ok",
        response_label="12 ms",
    )


@pytest.fixture
def configured_health_routes(monkeypatch: pytest.MonkeyPatch) -> RecordingTemplates:
    templates = RecordingTemplates()

    async def _sidebar_counts(_session: object) -> tuple[int, int]:
        return 2, 1

    def _badge_response(
        _request: object,
        _user: object,
        *,
        count: int,
        badge_classes: str,
    ) -> SimpleNamespace:
        return SimpleNamespace(count=count, badge_classes=badge_classes, status_code=200)

    monkeypatch.setattr(health_routes, "_get_templates", lambda: templates)
    monkeypatch.setattr(
        health_routes,
        "_build_context",
        lambda request, user=None, **kwargs: {"request": request, "user": user, **kwargs},
    )
    monkeypatch.setattr(health_routes, "_dashboard_gauge_offset_impl", lambda value: value)
    monkeypatch.setattr(
        health_routes,
        "_dashboard_relative_time_label_impl",
        lambda value, reference: f"{int((reference - value).total_seconds())}s ago",
    )
    monkeypatch.setattr(
        health_routes,
        "_download_client_type_label_impl",
        lambda client_type: client_type.upper(),
    )
    monkeypatch.setattr(health_routes, "_sidebar_badge_response_impl", _badge_response)
    monkeypatch.setattr(health_routes, "_load_sidebar_health_counts_impl", _sidebar_counts)
    return templates


@pytest.fixture
def route_request() -> SimpleNamespace:
    return SimpleNamespace(headers={}, cookies={}, state=SimpleNamespace())


def test_configure_health_routes_sets_runtime_dependencies() -> None:
    templates = RecordingTemplates()
    originals = {
        "_get_templates": health_routes._get_templates,
        "_build_context": health_routes._build_context,
        "_dashboard_gauge_offset_impl": health_routes._dashboard_gauge_offset_impl,
        "_dashboard_relative_time_label_impl": health_routes._dashboard_relative_time_label_impl,
        "_download_client_type_label_impl": health_routes._download_client_type_label_impl,
        "_sidebar_badge_response_impl": health_routes._sidebar_badge_response_impl,
        "_load_sidebar_health_counts_impl": health_routes._load_sidebar_health_counts_impl,
    }

    async def _counts(_session: object) -> tuple[int, int]:
        return 0, 0

    try:
        health_routes.configure_health_routes(
            get_templates=lambda: templates,
            build_context=lambda request, user=None, **kwargs: {
                "request": request,
                "user": user,
                **kwargs,
            },
            dashboard_gauge_offset=lambda value: value + 1,
            dashboard_relative_time_label=lambda _value, _reference: "relative",
            download_client_type_label=lambda value: value.title(),
            sidebar_badge_response=lambda _request, _user, **kwargs: SimpleNamespace(**kwargs),
            load_sidebar_health_counts=_counts,
        )

        assert health_routes._templates() is templates
        assert health_routes._dashboard_gauge_offset(2) == 3
        now = datetime(2026, 1, 1, tzinfo=UTC)
        assert health_routes._dashboard_relative_time_label(now, now) == "relative"
        assert health_routes._download_client_type_label("sabnzbd") == "Sabnzbd"
    finally:
        for name, value in originals.items():
            setattr(health_routes, name, value)


@pytest.mark.parametrize(
    ("attribute", "callable_name", "error"),
    [
        ("_get_templates", "_templates", "templates"),
        ("_build_context", "_ctx", "context builder"),
        ("_dashboard_gauge_offset_impl", "_dashboard_gauge_offset", "dashboard gauge helper"),
        (
            "_dashboard_relative_time_label_impl",
            "_dashboard_relative_time_label",
            "relative time helper",
        ),
        (
            "_download_client_type_label_impl",
            "_download_client_type_label",
            "download client label helper",
        ),
        ("_sidebar_badge_response_impl", "_sidebar_badge_response", "sidebar badge helper"),
        (
            "_load_sidebar_health_counts_impl",
            "_load_sidebar_health_counts",
            "sidebar health counts",
        ),
    ],
)
@pytest.mark.asyncio
async def test_health_runtime_dependency_guards(
    monkeypatch: pytest.MonkeyPatch,
    db_session,
    attribute: str,
    callable_name: str,
    error: str,
) -> None:
    monkeypatch.setattr(health_routes, attribute, None)
    callable_obj = getattr(health_routes, callable_name)

    with pytest.raises(RuntimeError, match=error):
        if callable_name == "_ctx":
            callable_obj(SimpleNamespace())
        elif callable_name == "_dashboard_relative_time_label":
            now = datetime(2026, 1, 1, tzinfo=UTC)
            callable_obj(now, now)
        elif callable_name == "_sidebar_badge_response":
            callable_obj(SimpleNamespace(), None, count=1, badge_classes="badge")
        elif callable_name == "_load_sidebar_health_counts":
            await callable_obj(db_session)
        elif callable_name in {"_dashboard_gauge_offset", "_download_client_type_label"}:
            callable_obj("qbittorrent" if "download" in error else 1)
        else:
            callable_obj()


@pytest.mark.asyncio
async def test_health_overview_routes_render_templates(
    configured_health_routes: RecordingTemplates,
    monkeypatch: pytest.MonkeyPatch,
    db_session,
    route_request: SimpleNamespace,
) -> None:
    async def _overview(_session: object, **options: object) -> tuple[str, HealthMonitoringView]:
        assert options == {}
        return "healthy", _health_view()

    monkeypatch.setattr(health_routes, "_load_health_overview", _overview)

    page = await health_routes.health_page(
        route_request,
        user=SimpleNamespace(username="admin"),
        session=db_session,
    )
    status = await health_routes.health_status_partial(
        route_request,
        user=SimpleNamespace(username="admin"),
        session=db_session,
    )

    assert page.template_name == "pages/health.html"
    assert status.template_name == "partials/health_status_region.html"
    assert page.context["overall_status"] == "healthy"
    assert status.context["health_view"].overall_status == "healthy"
    assert configured_health_routes.calls[-2][0] == "pages/health.html"
    assert configured_health_routes.calls[-1][0] == "partials/health_status_region.html"


@pytest.mark.asyncio
async def test_health_badge_partial_uses_unhealthy_badge_class(
    configured_health_routes: RecordingTemplates,
    db_session,
    route_request: SimpleNamespace,
) -> None:
    response = await health_routes.health_badge_partial(
        route_request,
        user=SimpleNamespace(username="admin"),
        session=db_session,
    )

    assert response.count == 3
    assert response.badge_classes == "count-badge-error"


@pytest.mark.asyncio
async def test_health_download_client_registry_routes(
    configured_health_routes: RecordingTemplates,
    monkeypatch: pytest.MonkeyPatch,
    db_session,
    route_request: SimpleNamespace,
) -> None:
    component = _component("download_clients")

    async def _overview(_session: object, **_options: object) -> tuple[str, HealthMonitoringView]:
        return "degraded", _health_view()

    async def _rows(_session: object) -> tuple[str, ...]:
        return ("client-row",)

    monkeypatch.setattr(health_routes, "_load_health_overview", _overview)
    monkeypatch.setattr(
        health_routes, "_select_health_component_view", lambda _view, _key: component
    )
    monkeypatch.setattr(health_routes, "_build_download_client_registry_rows", _rows)
    monkeypatch.setattr(
        health_routes,
        "_build_health_component_footer_items",
        lambda item: ({"label": item.display_name, "value": item.status},),
    )

    status = await health_routes.health_download_clients_status_partial(
        route_request,
        user=SimpleNamespace(username="admin"),
        session=db_session,
    )
    page = await health_routes.health_download_clients_page(
        route_request,
        user=SimpleNamespace(username="admin"),
        session=db_session,
    )

    assert status.template_name == "partials/health_download_clients_content_bundle.html"
    assert status.headers["HX-Replace-Url"] == "/health/download_clients"
    assert status.context["health_client_rows"] == ("client-row",)
    assert page.template_name == "pages/health_download_clients.html"
    assert page.context["health_component"] is component


@pytest.mark.asyncio
async def test_health_download_client_detail_routes(
    configured_health_routes: RecordingTemplates,
    monkeypatch: pytest.MonkeyPatch,
    db_session,
    route_request: SimpleNamespace,
) -> None:
    component = _component("sabnzbd")

    async def _health_data(_session: object) -> tuple[list[object], str]:
        return [], "unhealthy"

    async def _detail(_session: object, **kwargs: object) -> HealthComponentView:
        assert kwargs["subject_key"] == "sabnzbd"
        assert kwargs["history_page"] == 3
        assert kwargs["history_sort"] == "status"
        assert kwargs["history_search"] == "timeout"
        return component

    monkeypatch.setattr(health_routes, "_load_health_data", _health_data)
    monkeypatch.setattr(health_routes, "_build_download_client_detail_view", _detail)
    monkeypatch.setattr(
        health_routes,
        "_build_health_component_footer_items",
        lambda item: ({"label": item.display_name, "value": item.status},),
    )

    status = await health_routes.health_download_client_status_partial(
        route_request,
        user=SimpleNamespace(username="admin"),
        session=db_session,
        subject_key="sabnzbd",
        history_page=3,
        sort="status",
        search="timeout",
    )
    page = await health_routes.health_download_client_page(
        route_request,
        user=SimpleNamespace(username="admin"),
        session=db_session,
        subject_key="sabnzbd",
        history_page=3,
        sort="status",
        search="timeout",
    )

    assert status.template_name == "partials/health_component_content_bundle.html"
    assert status.headers["HX-Replace-Url"].startswith("/health/sabnzbd?")
    assert status.context["overall_status"] == "unhealthy"
    assert page.template_name == "pages/health_component.html"
    assert page.context["health_component"] is component


@pytest.mark.asyncio
async def test_health_indexer_registry_routes(
    configured_health_routes: RecordingTemplates,
    monkeypatch: pytest.MonkeyPatch,
    db_session,
    route_request: SimpleNamespace,
) -> None:
    component = _component("indexers")

    async def _overview(_session: object, **_options: object) -> tuple[str, HealthMonitoringView]:
        return "healthy", _health_view()

    async def _rows(_session: object) -> tuple[tuple[str, ...], tuple[str, ...]]:
        return ("prowlarr-row",), ("indexer-row",)

    monkeypatch.setattr(health_routes, "_load_health_overview", _overview)
    monkeypatch.setattr(
        health_routes, "_select_health_component_view", lambda _view, _key: component
    )
    monkeypatch.setattr(health_routes, "_build_indexer_registry_rows", _rows)
    monkeypatch.setattr(
        health_routes,
        "_build_health_component_footer_items",
        lambda item: ({"label": item.display_name, "value": item.status},),
    )

    status = await health_routes.health_indexers_status_partial(
        route_request,
        user=SimpleNamespace(username="admin"),
        session=db_session,
    )
    page = await health_routes.health_indexers_page(
        route_request,
        user=SimpleNamespace(username="admin"),
        session=db_session,
    )

    assert status.template_name == "partials/health_indexers_content_bundle.html"
    assert status.headers["HX-Replace-Url"] == "/health/indexers"
    assert status.context["health_proxy_rows"] == ("prowlarr-row",)
    assert status.context["health_indexer_rows"] == ("indexer-row",)
    assert page.template_name == "pages/health_indexers.html"


@pytest.mark.asyncio
async def test_health_indexer_detail_routes(
    configured_health_routes: RecordingTemplates,
    monkeypatch: pytest.MonkeyPatch,
    db_session,
    route_request: SimpleNamespace,
) -> None:
    component = _component("prowlarr")

    async def _health_data(_session: object) -> tuple[list[object], str]:
        return [], "degraded"

    async def _detail(_session: object, **kwargs: object) -> HealthComponentView:
        assert kwargs["subject_key"] == "prowlarr"
        assert kwargs["history_page"] == 4
        return component

    monkeypatch.setattr(health_routes, "_load_health_data", _health_data)
    monkeypatch.setattr(health_routes, "_build_indexer_detail_view", _detail)
    monkeypatch.setattr(
        health_routes,
        "_build_health_component_footer_items",
        lambda item: ({"label": item.display_name, "value": item.status},),
    )

    status = await health_routes.health_indexer_status_partial(
        route_request,
        user=SimpleNamespace(username="admin"),
        session=db_session,
        subject_key="prowlarr",
        history_page=4,
        sort="-checked_at",
        search="",
    )
    page = await health_routes.health_indexer_page(
        route_request,
        user=SimpleNamespace(username="admin"),
        session=db_session,
        subject_key="prowlarr",
        history_page=4,
        sort="-checked_at",
        search="",
    )

    assert status.template_name == "partials/health_component_content_bundle.html"
    assert status.headers["HX-Replace-Url"].startswith("/health/prowlarr?")
    assert page.template_name == "pages/health_component.html"
    assert page.context["overall_status"] == "degraded"


@pytest.mark.asyncio
async def test_health_generic_component_routes_pass_history_options(
    configured_health_routes: RecordingTemplates,
    monkeypatch: pytest.MonkeyPatch,
    db_session,
    route_request: SimpleNamespace,
) -> None:
    captured_options: list[dict[str, object]] = []
    component = _component("database")

    async def _overview(_session: object, **options: object) -> tuple[str, HealthMonitoringView]:
        captured_options.append(options)
        return "healthy", _health_view()

    monkeypatch.setattr(health_routes, "_load_health_overview", _overview)
    monkeypatch.setattr(
        health_routes, "_select_health_component_view", lambda _view, _key: component
    )
    monkeypatch.setattr(
        health_routes,
        "_build_health_component_footer_items",
        lambda item: ({"label": item.display_name, "value": item.status},),
    )

    status = await health_routes.health_component_status_partial(
        route_request,
        user=SimpleNamespace(username="admin"),
        session=db_session,
        component_key="database",
        history_page=5,
        sort="status",
        search="disk",
    )
    page = await health_routes.health_component_page(
        route_request,
        user=SimpleNamespace(username="admin"),
        session=db_session,
        component_key="database",
        history_page=6,
        sort="-checked_at",
        search="",
    )

    assert status.template_name == "partials/health_component_content_bundle.html"
    assert status.headers["HX-Replace-Url"].startswith("/health/database?")
    assert page.template_name == "pages/health_component.html"
    assert captured_options[0] == {
        "detail_component_key": "database",
        "detail_history_page": 5,
        "detail_history_sort": "status",
        "detail_history_search": "disk",
    }
    assert captured_options[1] == {
        "detail_component_key": "database",
        "detail_history_page": 6,
        "detail_history_sort": "-checked_at",
        "detail_history_search": "",
    }


@pytest.mark.asyncio
async def test_health_loaded_overview_and_view_builders_delegate(
    configured_health_routes: RecordingTemplates,
    monkeypatch: pytest.MonkeyPatch,
    db_session,
) -> None:
    health_view = _health_view()
    component = _component("database")

    async def _overview_loader(_session: object, **kwargs: object) -> SimpleNamespace:
        assert kwargs["load_health_data"] is health_routes._load_health_data
        assert kwargs["build_health_view"] is health_routes._build_health_view
        assert kwargs["detail_component_key"] == "database"
        return SimpleNamespace(overall_status="healthy", health_view=health_view)

    async def _view_impl(_session: object, **kwargs: object) -> HealthMonitoringView:
        assert kwargs["gauge_offset"] is health_routes._dashboard_gauge_offset
        assert kwargs["relative_time_label"] is health_routes._dashboard_relative_time_label
        return health_view

    def _component_impl(**kwargs: object) -> HealthComponentView:
        assert kwargs["relative_time_label"] is health_routes._dashboard_relative_time_label
        return component

    monkeypatch.setattr(health_routes, "load_health_overview", _overview_loader)
    monkeypatch.setattr(health_routes, "_build_health_view_impl", _view_impl)
    monkeypatch.setattr(health_routes, "_build_health_component_view_impl", _component_impl)
    monkeypatch.setattr(
        health_routes, "_select_health_component_view_impl", lambda *_args: component
    )

    status, loaded_view = await health_routes._load_health_overview(
        db_session,
        detail_component_key="database",
    )
    built_view = await health_routes._build_health_view(
        db_session,
        components=[],
        overall_status="healthy",
        search_stats=SimpleNamespace(),
    )
    built_component = health_routes._build_health_component_view(
        component_key="database",
        component={"status": "healthy"},
        checks=(),
        history=(),
        history_page=1,
        history_total_pages=1,
        history_total_count=0,
        history_sort="-checked_at",
        history_search_query="",
        current_time=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert status == "healthy"
    assert loaded_view is health_view
    assert built_view is health_view
    assert built_component is component
    assert health_routes._select_health_component_view(health_view, "database") is component


@pytest.mark.asyncio
async def test_health_helper_wrappers_delegate(
    configured_health_routes: RecordingTemplates,
    monkeypatch: pytest.MonkeyPatch,
    db_session,
) -> None:
    component = _component("database")
    check = _check_item()
    history = HealthHistoryRowView(
        key="row",
        time_label="now",
        check_name="Database",
        status_label="Healthy",
        pill_tone="pill-success",
        response_label="12 ms",
    )

    async def _prowlarr_config(_session: object) -> str:
        return "https://prowlarr.local"

    async def _download_rows(_session: object, **kwargs: object) -> tuple[str, ...]:
        assert kwargs["download_client_type_label"] is health_routes._download_client_type_label
        return ("download-row",)

    async def _indexer_rows(_session: object, **kwargs: object) -> tuple[str, tuple[str, ...]]:
        assert kwargs["relative_time_label"] is health_routes._dashboard_relative_time_label
        return "prowlarr-row", ("indexer-row",)

    async def _download_detail(_session: object, **kwargs: object) -> HealthComponentView:
        assert kwargs["download_client_type_label"] is health_routes._download_client_type_label
        return component

    async def _indexer_detail(_session: object, **kwargs: object) -> HealthComponentView:
        assert kwargs["relative_time_label"] is health_routes._dashboard_relative_time_label
        return component

    monkeypatch.setattr(
        health_routes,
        "build_health_component_footer_items",
        lambda item: ({"label": item.display_name, "value": item.status},),
    )
    monkeypatch.setattr(
        health_routes, "download_client_endpoint_summary", lambda url: ("http", url, "1")
    )
    monkeypatch.setattr(health_routes, "build_download_client_placeholder_checks", lambda: (check,))
    monkeypatch.setattr(health_routes, "health_response_or_dash", lambda value: f"{value} ms")
    monkeypatch.setattr(health_routes, "load_prowlarr_route_config", _prowlarr_config)
    monkeypatch.setattr(health_routes, "indexer_endpoint_summary", lambda url: ("https", url, "2"))
    monkeypatch.setattr(health_routes, "indexer_kind_detail_label", lambda value: value.upper())
    monkeypatch.setattr(health_routes, "indexer_content_type_label", lambda value: value.title())
    monkeypatch.setattr(health_routes, "build_prowlarr_placeholder_checks", lambda: (check,))
    monkeypatch.setattr(health_routes, "build_indexer_placeholder_checks", lambda: (check,))
    monkeypatch.setattr(health_routes, "build_download_client_registry_rows", _download_rows)
    monkeypatch.setattr(health_routes, "build_indexer_registry_rows", _indexer_rows)
    monkeypatch.setattr(health_routes, "build_download_client_detail_view", _download_detail)
    monkeypatch.setattr(health_routes, "build_indexer_detail_view", _indexer_detail)
    monkeypatch.setattr(health_routes, "build_health_checks_from_details", lambda details: (check,))
    monkeypatch.setattr(health_routes, "health_component_card_stats", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(
        health_routes, "health_component_detail_stats", lambda *_args, **_kwargs: ()
    )
    monkeypatch.setattr(
        health_routes, "health_attention_label", lambda _checks, *, down_noun: down_noun
    )
    monkeypatch.setattr(
        health_routes,
        "health_component_sublabel",
        lambda component_key, _checks, _details: component_key,
    )

    assert health_routes._build_health_component_footer_items(component) == (
        {"label": "Database", "value": "healthy"},
    )
    assert health_routes._download_client_endpoint_summary("localhost") == (
        "http",
        "localhost",
        "1",
    )
    assert health_routes._download_client_placeholder_checks() == (check,)
    assert health_routes._health_response_or_dash(12) == "12 ms"
    assert await health_routes._load_prowlarr_route_config(db_session) == "https://prowlarr.local"
    assert health_routes._indexer_endpoint_summary("indexer.local") == (
        "https",
        "indexer.local",
        "2",
    )
    assert health_routes._indexer_kind_detail_label("torznab") == "TORZNAB"
    assert health_routes._indexer_content_type_label("comic") == "Comic"
    assert health_routes._prowlarr_placeholder_checks() == (check,)
    assert health_routes._indexer_placeholder_checks() == (check,)
    assert await health_routes._build_download_client_registry_rows(db_session) == ("download-row",)
    assert await health_routes._build_indexer_registry_rows(db_session) == (
        "prowlarr-row",
        ("indexer-row",),
    )
    assert (
        await health_routes._build_download_client_detail_view(
            db_session,
            subject_key="sab",
            current_time=datetime(2026, 1, 1, tzinfo=UTC),
            history_page=1,
            history_sort="-checked_at",
            history_search="",
        )
    ) is component
    assert (
        await health_routes._build_indexer_detail_view(
            db_session,
            subject_key="prowlarr",
            current_time=datetime(2026, 1, 1, tzinfo=UTC),
            history_page=1,
            history_sort="-checked_at",
            history_search="",
        )
    ) is component
    assert health_routes._health_checks_from_details({"checks": []}) == (check,)
    assert (
        health_routes._health_component_card_stats(
            "database",
            checks=(check,),
            response_ms=12,
            last_checked=None,
            current_time=datetime(2026, 1, 1, tzinfo=UTC),
            details={},
            message="ok",
        )
        == ()
    )
    assert (
        health_routes._health_component_detail_stats(
            "database",
            checks=(check,),
            response_ms=12,
            last_checked=None,
            current_time=datetime(2026, 1, 1, tzinfo=UTC),
            details={},
            message="ok",
        )
        == ()
    )
    assert health_routes._health_attention_label((check,), down_noun="indexers") == "indexers"
    assert (
        health_routes._health_component_sublabel("database", (check,), {"history": history})
        == "database"
    )
