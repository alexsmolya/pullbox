"""Public unauthenticated UI routes."""

from collections.abc import Callable, Mapping

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.responses import Response

from pullbox.api.deps import CurrentUser, DbSession
from pullbox.api.v1.auth import attach_session_cookie, authenticate_login_request
from pullbox.core.exceptions import AuthenticationError, LoginRateLimitError
from pullbox.schemas.auth import LoginRequest
from pullbox.ui.standalone_shell import standalone_shell_version

router = APIRouter()
session_router = APIRouter()

_LOGIN_STANDALONE_SHELL_TEMPLATES = (
    "pages/login.html",
    "components/setup_brand_lockup.html",
)
_SETUP_STANDALONE_SHELL_TEMPLATES = (
    "pages/setup_initial.html",
    "components/setup_brand_lockup.html",
)

_GetTemplates = Callable[[], Jinja2Templates]
_BuildContext = Callable[..., dict[str, object]]

_get_templates: _GetTemplates | None = None
_build_context: _BuildContext | None = None


def configure_public_routes(
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
        msg = "public routes have not been configured with templates"
        raise RuntimeError(msg)
    return _get_templates()


def _ctx(request: Request, **kwargs: object) -> dict[str, object]:
    if _build_context is None:
        msg = "public routes have not been configured with a context builder"
        raise RuntimeError(msg)
    context: Mapping[str, object] = _build_context(request, **kwargs)
    return dict(context)


def _login_context(
    request: Request,
    *,
    login_error: str = "",
    login_username: str = "",
) -> dict[str, object]:
    shell_version = standalone_shell_version(*_LOGIN_STANDALONE_SHELL_TEMPLATES)
    return _ctx(
        request,
        standalone_shell_version=shell_version,
        login_error=login_error,
        login_username=login_username,
    )


@session_router.api_route("/logout", methods=["GET", "POST"], include_in_schema=False)
async def ui_logout(request: Request) -> Response:
    """Clear the session cookie and redirect to the login page."""
    from pullbox.api.deps import is_secure_request
    from pullbox.services.auth_service import SESSION_COOKIE_NAME

    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        httponly=True,
        samesite="lax",
        secure=is_secure_request(request),
        path="/",
    )
    return response


@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
async def login_page(request: Request, user: CurrentUser) -> Response:
    """Render the login page. Redirects to dashboard if already authenticated."""
    if user is not None:
        return RedirectResponse(url="/", status_code=302)
    return _templates().TemplateResponse(
        request,
        "pages/login.html",
        _login_context(request),
    )


@router.post("/login", response_class=HTMLResponse, include_in_schema=False)
async def login_form(
    request: Request,
    session: DbSession,
    username: str = Form(""),
    password: str = Form(""),
) -> Response:
    """Authenticate a standard HTML login form for non-JavaScript clients."""
    normalized_username = username.strip()
    if not normalized_username or not password:
        return _templates().TemplateResponse(
            request,
            "pages/login.html",
            _login_context(
                request,
                login_error="Enter your username and password.",
                login_username=normalized_username,
            ),
            status_code=400,
        )

    try:
        login_result = await authenticate_login_request(
            request,
            LoginRequest(username=normalized_username, password=password),
            session,
        )
    except LoginRateLimitError as exc:
        return _templates().TemplateResponse(
            request,
            "pages/login.html",
            _login_context(
                request,
                login_error=exc.message,
                login_username=normalized_username,
            ),
            status_code=exc.status_code,
        )
    except AuthenticationError as exc:
        return _templates().TemplateResponse(
            request,
            "pages/login.html",
            _login_context(
                request,
                login_error=exc.message,
                login_username=normalized_username,
            ),
            status_code=exc.status_code,
        )

    response = RedirectResponse(url="/", status_code=303)
    attach_session_cookie(
        response,
        login_result.user_id,
        request,
        session_lifetime_hours=login_result.session_lifetime_hours,
        session_version=login_result.session_version,
    )
    return response


@router.get("/setup", response_class=HTMLResponse, include_in_schema=False)
async def setup_page(request: Request, session: DbSession) -> Response:
    """Render the first-run setup page or send completed installs to login."""
    from pullbox.api.middleware import is_setup_complete, is_setup_complete_db

    if is_setup_complete() or await is_setup_complete_db(session):
        return RedirectResponse(url="/login", status_code=302)
    shell_version = standalone_shell_version(*_SETUP_STANDALONE_SHELL_TEMPLATES)

    return _templates().TemplateResponse(
        request,
        "pages/setup_initial.html",
        _ctx(
            request,
            standalone_shell_version=shell_version,
        ),
    )
