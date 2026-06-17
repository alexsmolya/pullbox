"""Focused branch coverage for public unauthenticated UI routes."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from pullbox.core.exceptions import AuthenticationError, LoginRateLimitError
from pullbox.ui import public_routes


class RecordingTemplates:
    """Tiny templates stand-in that records public route renders."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object], dict[str, object]]] = []

    def TemplateResponse(  # noqa: N802 - mirrors Starlette's template API.
        self,
        _request: object,
        template_name: str,
        context: dict[str, object],
        **kwargs: object,
    ) -> SimpleNamespace:
        response = SimpleNamespace(
            template_name=template_name,
            context=context,
            status_code=kwargs.get("status_code", 200),
            headers={},
        )
        self.calls.append((template_name, context, kwargs))
        return response


@pytest.fixture
def configured_public_routes(monkeypatch: pytest.MonkeyPatch) -> RecordingTemplates:
    templates = RecordingTemplates()
    monkeypatch.setattr(public_routes, "_get_templates", lambda: templates)
    monkeypatch.setattr(
        public_routes,
        "_build_context",
        lambda request, **kwargs: {"request": request, **kwargs},
    )
    monkeypatch.setattr(public_routes, "standalone_shell_version", lambda *_templates: "shell-v1")
    return templates


@pytest.fixture
def route_request() -> SimpleNamespace:
    return SimpleNamespace(
        headers={}, cookies={}, state=SimpleNamespace(), url=SimpleNamespace(scheme="http")
    )


@pytest.mark.parametrize(
    ("attribute", "callable_name", "error"),
    [
        ("_get_templates", "_templates", "templates"),
        ("_build_context", "_ctx", "context builder"),
    ],
)
def test_public_runtime_dependency_guards(
    monkeypatch: pytest.MonkeyPatch,
    attribute: str,
    callable_name: str,
    error: str,
) -> None:
    monkeypatch.setattr(public_routes, attribute, None)
    callable_obj = getattr(public_routes, callable_name)

    with pytest.raises(RuntimeError, match=error):
        if callable_name == "_ctx":
            callable_obj(SimpleNamespace())
        else:
            callable_obj()


def test_configure_public_routes_sets_runtime_dependencies() -> None:
    templates = RecordingTemplates()
    originals = {
        "_get_templates": public_routes._get_templates,
        "_build_context": public_routes._build_context,
    }
    try:
        public_routes.configure_public_routes(
            get_templates=lambda: templates,
            build_context=lambda request, **kwargs: {"request": request, **kwargs},
        )

        assert public_routes._templates() is templates
        assert public_routes._ctx(SimpleNamespace(), marker=True)["marker"] is True
    finally:
        for name, value in originals.items():
            setattr(public_routes, name, value)


@pytest.mark.asyncio
async def test_logout_redirects_and_clears_cookie(route_request: SimpleNamespace) -> None:
    response = await public_routes.ui_logout(route_request)

    assert response.status_code == 302
    assert response.headers["location"] == "/login"
    assert "session=" in response.headers["set-cookie"]
    assert "Max-Age=0" in response.headers["set-cookie"]


@pytest.mark.asyncio
async def test_login_page_redirects_authenticated_and_renders_anonymous(
    configured_public_routes: RecordingTemplates,
    route_request: SimpleNamespace,
) -> None:
    redirect = await public_routes.login_page(route_request, user=SimpleNamespace(id=1))
    rendered = await public_routes.login_page(route_request, user=None)

    assert redirect.status_code == 302
    assert redirect.headers["location"] == "/"
    assert rendered.template_name == "pages/login.html"
    assert rendered.context["standalone_shell_version"] == "shell-v1"


@pytest.mark.asyncio
async def test_login_form_handles_missing_credentials_and_auth_errors(
    configured_public_routes: RecordingTemplates,
    monkeypatch: pytest.MonkeyPatch,
    route_request: SimpleNamespace,
    db_session,
) -> None:
    missing = await public_routes.login_form(
        route_request,
        session=db_session,
        username=" admin ",
        password="",
    )
    assert missing.status_code == 400
    assert missing.context["login_error"] == "Enter your username and password."
    assert missing.context["login_username"] == "admin"

    async def _rate_limited(*_args: object, **_kwargs: object) -> object:
        raise LoginRateLimitError(retry_after_seconds=30, message="Too many attempts.")

    monkeypatch.setattr(public_routes, "authenticate_login_request", _rate_limited)
    limited = await public_routes.login_form(
        route_request,
        session=db_session,
        username="admin",
        password="wrong",
    )
    assert limited.status_code == 429
    assert limited.context["login_error"] == "Too many attempts."

    async def _auth_failed(*_args: object, **_kwargs: object) -> object:
        raise AuthenticationError("Bad credentials.")

    monkeypatch.setattr(public_routes, "authenticate_login_request", _auth_failed)
    failed = await public_routes.login_form(
        route_request,
        session=db_session,
        username="admin",
        password="wrong",
    )
    assert failed.status_code == 401
    assert failed.context["login_error"] == "Bad credentials."


@pytest.mark.asyncio
async def test_login_form_redirects_and_attaches_session_cookie(
    configured_public_routes: RecordingTemplates,
    monkeypatch: pytest.MonkeyPatch,
    route_request: SimpleNamespace,
    db_session,
) -> None:
    captured_cookie: list[dict[str, object]] = []

    async def _authenticated(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(user_id=7, session_lifetime_hours=24, session_version=3)

    def _attach_cookie(response: object, user_id: int, _request: object, **kwargs: object) -> None:
        captured_cookie.append({"user_id": user_id, **kwargs})
        response.headers["set-cookie"] = "session=fake"

    monkeypatch.setattr(public_routes, "authenticate_login_request", _authenticated)
    monkeypatch.setattr(public_routes, "attach_session_cookie", _attach_cookie)

    response = await public_routes.login_form(
        route_request,
        session=db_session,
        username=" admin ",
        password="TestPassword1!",
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert response.headers["set-cookie"] == "session=fake"
    assert captured_cookie == [{"user_id": 7, "session_lifetime_hours": 24, "session_version": 3}]


@pytest.mark.asyncio
async def test_setup_page_redirects_when_complete_or_renders_first_run(
    configured_public_routes: RecordingTemplates,
    monkeypatch: pytest.MonkeyPatch,
    route_request: SimpleNamespace,
    db_session,
) -> None:
    from pullbox.api import middleware

    monkeypatch.setattr(middleware, "is_setup_complete", lambda: True)
    complete = await public_routes.setup_page(route_request, session=db_session)
    assert complete.status_code == 302
    assert complete.headers["location"] == "/login"

    async def _db_incomplete(_session: object) -> bool:
        return False

    monkeypatch.setattr(middleware, "is_setup_complete", lambda: False)
    monkeypatch.setattr(middleware, "is_setup_complete_db", _db_incomplete)
    first_run = await public_routes.setup_page(route_request, session=db_session)

    assert first_run.template_name == "pages/setup_initial.html"
    assert first_run.context["standalone_shell_version"] == "shell-v1"
