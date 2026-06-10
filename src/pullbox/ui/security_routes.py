"""Security UI routes and tab loading."""

from collections.abc import Callable, Mapping

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from starlette.responses import Response

from pullbox.api.deps import AuthenticatedUser, DbSession
from pullbox.core.config_resolver import load_system_config_values
from pullbox.models.config import SystemConfig

page_router = APIRouter()
htmx_router = APIRouter()

SECURITY_TABS: tuple[dict[str, str], ...] = (
    {
        "key": "authentication",
        "label": "Authentication",
        "icon": "M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z",  # noqa: E501
    },
    {
        "key": "api_access",
        "label": "API Access",
        "icon": "M15.75 5.25a3 3 0 013 3m3 0a6 6 0 01-7.029 5.912c-.563-.097-1.159.026-1.563.43L10.5 17.25H8.25v2.25H6v2.25H2.25v-2.818c0-.597.237-1.17.659-1.591l6.499-6.499c.404-.404.527-1 .43-1.563A6 6 0 1121.75 8.25z",  # noqa: E501
    },
    {
        "key": "file_safety",
        "label": "File Safety",
        "icon": "M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z",  # noqa: E501
    },
    {
        "key": "audit_log",
        "label": "Audit Log",
        "icon": "M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m5.231 13.481L15 17.25m-4.5-15H5.625c-.621 0-1.125.504-1.125 1.125v16.5c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9zm3.75 11.625a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z",  # noqa: E501
    },
)

_SECURITY_TABS = ("authentication", "api_access", "file_safety", "audit_log")

_GetTemplates = Callable[[], Jinja2Templates]
_BuildContext = Callable[..., dict[str, object]]

_get_templates: _GetTemplates | None = None
_build_context: _BuildContext | None = None


def configure_security_routes(
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
        msg = "security routes have not been configured with templates"
        raise RuntimeError(msg)
    return _get_templates()


def _ctx(request: Request, user: object | None = None, **kwargs: object) -> dict[str, object]:
    if _build_context is None:
        msg = "security routes have not been configured with a context builder"
        raise RuntimeError(msg)
    context: Mapping[str, object] = _build_context(request, user, **kwargs)
    return dict(context)


async def load_security_tab(session: DbSession, tab: str) -> dict[str, object]:
    """Load data needed for a security tab."""
    ctx: dict[str, object] = {}

    if tab == "authentication":
        ctx["configs"] = await load_system_config_values(
            session,
            (
                "local_auth_bypass_enabled",
                "local_auth_bypass_addresses",
                "local_auth_bypass_username",
                "session_lifetime_hours",
            ),
        )
    elif tab == "file_safety":
        cfg_result = await session.execute(
            select(SystemConfig).where(
                SystemConfig.key.in_(
                    [
                        "allowed_import_extensions",
                        "block_dangerous_files",
                        "archive_size_limit_mb",
                    ]
                )
            )
        )
        ctx["configs"] = {c.key: c.value for c in cfg_result.scalars().all()}

    return ctx


def _normalize_security_tab(tab: str) -> str:
    if tab not in _SECURITY_TABS:
        return "authentication"
    return tab


@page_router.get("/security", response_class=HTMLResponse, include_in_schema=False)
async def security_page(
    request: Request,
    user: AuthenticatedUser,
    session: DbSession,
    tab: str = Query("authentication"),
) -> Response:
    """Render the security page with tabbed interface."""
    tab = _normalize_security_tab(tab)
    tab_data = await load_security_tab(session, tab)
    return _templates().TemplateResponse(
        request,
        "pages/security.html",
        _ctx(request, user, tab=tab, security_tabs=SECURITY_TABS, **tab_data),
    )


@htmx_router.get("/htmx/security/{tab}", response_class=HTMLResponse, include_in_schema=False)
async def htmx_security_tab(
    request: Request,
    tab: str,
    user: AuthenticatedUser,
    session: DbSession,
) -> Response:
    """Load a security tab partial via HTMX."""
    tab = _normalize_security_tab(tab)
    tab_data = await load_security_tab(session, tab)
    return _templates().TemplateResponse(
        request,
        "partials/security_content_bundle.html",
        _ctx(request, user, tab=tab, security_tabs=SECURITY_TABS, **tab_data),
    )
