"""FastAPI dependency injection — database sessions, auth, and settings."""

from collections.abc import AsyncGenerator
from typing import Annotated

import structlog
from fastapi import Cookie, Depends, Header, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pullbox.config import PullboxSettings, get_settings
from pullbox.core.config_resolver import get_int_setting, load_system_config_values
from pullbox.core.exceptions import AuthenticationError
from pullbox.core.local_auth_bypass import (
    LocalAuthBypassResolution,
    is_local_address,
    local_bypass_policy_from_mapping,
    resolve_client_ip,
    resolve_local_auth_bypass,
)
from pullbox.database import get_db as _get_db
from pullbox.database import get_session_factory
from pullbox.models.health import HealthCurrentStatus, HealthStatus
from pullbox.models.import_job import ImportedSeries, ImportJob, ImportJobStatus, ImportSeriesStatus
from pullbox.models.pending_match import PendingMatch, PendingMatchStatus
from pullbox.models.user import User
from pullbox.services.auth_service import SESSION_COOKIE_NAME, AuthService


def is_secure_request(request: Request) -> bool:
    """Determine if the current request arrived over HTTPS.

    Checks the request URL scheme and the X-Forwarded-Proto header
    (set by reverse proxies like nginx/traefik). Returns True only
    when the connection is genuinely HTTPS — never forces Secure
    cookies on plain HTTP connections.
    """
    if request.url.scheme == "https":
        return True
    forwarded = request.headers.get("x-forwarded-proto", "")
    if forwarded.lower() != "https":
        return False

    raw_client_ip = request.client.host if request.client is not None else ""
    trusted_proxies = {
        proxy.strip() for proxy in get_settings().trusted_proxies.split(",") if proxy.strip()
    }
    return bool(raw_client_ip and raw_client_ip in trusted_proxies)


logger = structlog.get_logger(__name__)


def _should_prime_sidebar_context(request: Request) -> bool:
    """Return True when this request should preload sidebar badge state."""
    path = request.url.path
    if request.method != "GET":
        return False
    return not (path.startswith("/api/") or path.startswith("/htmx/") or path == "/health/badge")


async def load_sidebar_health_counts(session: AsyncSession) -> tuple[int, int]:
    """Return degraded and unhealthy health counts for the sidebar badge."""
    latest_result = await session.execute(
        select(HealthCurrentStatus.status).where(
            HealthCurrentStatus.is_summary.is_(True),
            HealthCurrentStatus.subject_key_norm == "",
        )
    )
    statuses = list(latest_result.scalars().all())
    degraded = sum(1 for status in statuses if status == HealthStatus.DEGRADED)
    unhealthy = sum(1 for status in statuses if status == HealthStatus.UNHEALTHY)
    return degraded, unhealthy


async def _build_sidebar_context(session: AsyncSession) -> dict[str, int]:
    """Load the initial sidebar badge state for full-page UI renders."""
    pending_match_count: int = (
        await session.execute(
            select(func.count(PendingMatch.id)).where(
                PendingMatch.status == PendingMatchStatus.PENDING
            )
        )
    ).scalar_one()

    orphaned_count: int = (
        await session.execute(
            select(func.count())
            .select_from(ImportedSeries)
            .join(ImportJob, ImportedSeries.import_job_id == ImportJob.id)
            .where(
                ImportedSeries.status.in_(
                    [
                        ImportSeriesStatus.NO_MATCH,
                        ImportSeriesStatus.RECOVERY_PENDING,
                    ]
                ),
                ImportJob.status == ImportJobStatus.COMPLETED,
            )
        )
    ).scalar() or 0

    health_degraded, health_unhealthy = await load_sidebar_health_counts(session)

    return {
        "pending_match_count": pending_match_count,
        "orphaned_count": orphaned_count,
        "health_degraded": health_degraded,
        "health_unhealthy": health_unhealthy,
    }


async def _prime_sidebar_context(request: Request, session: AsyncSession) -> None:
    """Populate request.state with shared sidebar badge data when needed."""
    if not _should_prime_sidebar_context(request):
        return
    if getattr(request.state, "sidebar_context", None) is not None:
        return
    request.state.sidebar_context = await _build_sidebar_context(session)


async def get_db_dep() -> AsyncGenerator[AsyncSession, None]:
    """Re-export database session dependency."""
    async for session in _get_db():
        yield session


def get_request_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    """Return the app-scoped session factory when available."""
    app_state = getattr(request.app, "state", None)
    factory = getattr(app_state, "db_session_factory", None)
    return factory or get_session_factory()


def get_settings_dep() -> PullboxSettings:
    """Return application settings."""
    return get_settings()


def _is_local_address(client_ip: str, local_addresses: str) -> bool:
    """Backwards-compatible re-export for tests and internal callers."""
    return is_local_address(client_ip, local_addresses)


def _resolve_client_ip(request: Request, trusted_proxies: str) -> str:
    """Backwards-compatible re-export for tests and internal callers."""
    return resolve_client_ip(request, trusted_proxies)


async def get_current_user(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_dep)],
    x_api_key: Annotated[str | None, Header()] = None,
    pullbox_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> User | None:
    """Resolve the current user from session cookie, API key, or local bypass.

    Returns None if no valid credentials are provided.
    """
    auth_config = await load_system_config_values(
        session,
        (
            "local_auth_bypass_addresses",
            "local_auth_bypass_enabled",
            "local_auth_bypass_username",
            "session_lifetime_hours",
        ),
    )
    session_lifetime_seconds = get_int_setting(auth_config, "session_lifetime_hours", 24) * 3600

    # Try session cookie first
    if pullbox_session:
        data = AuthService.validate_session_token(
            pullbox_session,
            max_age_seconds=session_lifetime_seconds,
        )
        if data is not None:
            user_id = data.get("user_id")
            if isinstance(user_id, int):
                result = await session.execute(select(User).where(User.id == user_id))
                user = result.scalar_one_or_none()
                if user is not None:
                    # Check session version — reject if token is outdated
                    token_sv = data.get("sv", 0)
                    if not isinstance(token_sv, int):
                        token_sv = 0
                    if token_sv != user.session_version:
                        logger.warning(
                            "session_invalidated_version_mismatch",
                            user_id=user.id,
                        )
                        return None

                    # Check user is still active
                    if not user.is_active:
                        logger.warning(
                            "session_invalidated_user_inactive",
                            user_id=user.id,
                        )
                        return None

                    request.state.auth_method = "session"
                    csrf = data.get("csrf")
                    request.state.csrf_token = csrf if isinstance(csrf, str) else None
                    await _prime_sidebar_context(request, session)
                    return user

    # Try API key header
    if x_api_key:
        user = await AuthService.validate_api_key(session, x_api_key)
        if user is not None:
            request.state.auth_method = "api_key"
            request.state.csrf_token = None
            await _prime_sidebar_context(request, session)
            return user

    # Try local auth bypass
    settings = get_settings()
    bypass_resolution = getattr(request.state, "local_bypass_resolution", None)
    if not isinstance(bypass_resolution, LocalAuthBypassResolution):
        bypass_resolution = None
    if bypass_resolution is None:
        bypass_resolution = await resolve_local_auth_bypass(
            request,
            session,
            settings.trusted_proxies,
            policy=local_bypass_policy_from_mapping(auth_config),
        )
    if bypass_resolution.user_id is not None:
        result = await session.execute(select(User).where(User.id == bypass_resolution.user_id))
        user = result.scalar_one_or_none()
        if user is not None and user.is_active:
            request.state.auth_method = "local_bypass"
            request.state.csrf_token = bypass_resolution.csrf_token
            await _prime_sidebar_context(request, session)
            logger.info(
                "local_auth_bypass",
                client_ip=bypass_resolution.client_ip,
                user_id=user.id,
                username=user.username,
            )
            return user
    elif (
        bypass_resolution.enabled
        and bypass_resolution.client_ip
        and bypass_resolution.failure_reason not in {"disabled_or_unconfigured", "ip_not_allowed"}
    ):
        logger.warning(
            "local_auth_bypass_denied",
            client_ip=bypass_resolution.client_ip,
            failure_reason=bypass_resolution.failure_reason,
            configured_username=auth_config.get("local_auth_bypass_username", ""),
        )

    return None


async def require_auth(
    user: Annotated[User | None, Depends(get_current_user)],
) -> User:
    """Require an authenticated user. Raises 401 if not authenticated."""
    if user is None:
        raise AuthenticationError()
    return user


async def require_stream_auth(
    request: Request,
    x_api_key: Annotated[str | None, Header()] = None,
    pullbox_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> User:
    """Authenticate streaming routes without holding a DB session open."""
    factory = get_request_session_factory(request)
    async with factory() as session:
        user = await get_current_user(
            request,
            session,
            x_api_key=x_api_key,
            pullbox_session=pullbox_session,
        )
    if user is None:
        raise AuthenticationError()
    return user


async def require_interactive_auth(
    request: Request,
    user: Annotated[User | None, Depends(get_current_user)],
) -> User:
    """Require an interactive auth path (session or local bypass)."""
    if user is None:
        raise AuthenticationError()

    auth_method = getattr(request.state, "auth_method", None)
    if auth_method == "api_key":
        raise AuthenticationError("Interactive operator authentication required.")

    return user


# Annotated aliases for use in route signatures
DbSession = Annotated[AsyncSession, Depends(get_db_dep)]
CurrentUser = Annotated[User | None, Depends(get_current_user)]
# Route access classes:
# - Public: no auth dependency
# - AuthenticatedUser: automation-safe routes (session, API key, local bypass)
# - InteractiveOperatorUser: operator routes (session or local bypass only)
AuthenticatedUser = Annotated[User, Depends(require_auth)]
AuthenticatedStreamUser = Annotated[User, Depends(require_stream_auth)]
InteractiveOperatorUser = Annotated[User, Depends(require_interactive_auth)]
Settings = Annotated[PullboxSettings, Depends(get_settings_dep)]
