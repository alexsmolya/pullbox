"""Authentication API routes — login, logout, API keys, and first-run setup."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from pullbox.api.deps import (
    DbSession,
    InteractiveOperatorUser,
    is_secure_request,
)
from pullbox.api.middleware import mark_setup_complete
from pullbox.core.config_resolver import get_int_setting, load_system_config_values
from pullbox.core.exceptions import AuthenticationError, LoginRateLimitError
from pullbox.core.rate_limiter import LoginRateLimiter
from pullbox.models.audit_log import AuditEventType
from pullbox.models.user import APIKey, User
from pullbox.schemas.auth import (
    AccountUpdateRequest,
    AccountUpdateResponse,
    APIKeyCreate,
    APIKeyCreatedResponse,
    APIKeyResponse,
    LoginRequest,
    LoginResponse,
    PasswordPolicyResponse,
    PolicyRequirement,
    SetupAccountCreatedResponse,
    SetupRequest,
    UserResponse,
)
from pullbox.services.audit_service import (
    record_audit_event as _audit,
)
from pullbox.services.audit_service import (
    source_ip_from_request,
)
from pullbox.services.auth_service import SESSION_COOKIE_NAME, AuthService

if TYPE_CHECKING:
    from starlette.responses import Response

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["auth"])


_rate_limiter = LoginRateLimiter()


@dataclass(frozen=True)
class AuthenticatedLogin:
    """Detached login data safe to use after audit side effects."""

    user_id: int
    username: str
    is_active: bool
    session_version: int
    session_lifetime_hours: int

    @property
    def user_response(self) -> UserResponse:
        return UserResponse(id=self.user_id, username=self.username, is_active=self.is_active)


def _session_token_and_csrf(user_id: int, *, session_version: int = 0) -> tuple[str, str]:
    token = AuthService.create_session_token(user_id, session_version=session_version)
    csrf_token = AuthService.get_csrf_token_from_session(token) or ""
    return token, csrf_token


def _set_session_cookie(
    response: Response,
    request: Request,
    *,
    token: str,
    session_lifetime_hours: int,
) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=is_secure_request(request),
        max_age=session_lifetime_hours * 3600,
        path="/",
    )


def attach_session_cookie(
    response: Response,
    user_id: int,
    request: Request,
    *,
    session_lifetime_hours: int,
    session_version: int = 0,
) -> str:
    """Attach the signed session cookie and return its CSRF token."""
    token, csrf_token = _session_token_and_csrf(user_id, session_version=session_version)
    _set_session_cookie(
        response,
        request,
        token=token,
        session_lifetime_hours=session_lifetime_hours,
    )
    return csrf_token


def _build_session_response(
    user: User,
    request: Request,
    *,
    session_lifetime_hours: int,
    session_version: int = 0,
) -> JSONResponse:
    """Create a JSONResponse with login data and a session cookie."""
    token, csrf_token = _session_token_and_csrf(user.id, session_version=session_version)
    response_data = LoginResponse(
        user=UserResponse.model_validate(user),
        csrf_token=csrf_token,
    )
    response = JSONResponse(content=response_data.model_dump(mode="json"))
    _set_session_cookie(
        response,
        request,
        token=token,
        session_lifetime_hours=session_lifetime_hours,
    )
    return response


def _build_login_session_response(
    login_result: AuthenticatedLogin,
    request: Request,
) -> JSONResponse:
    """Create a JSON login response from detached login data."""
    token, csrf_token = _session_token_and_csrf(
        login_result.user_id,
        session_version=login_result.session_version,
    )
    response_data = LoginResponse(
        user=login_result.user_response,
        csrf_token=csrf_token,
    )
    response = JSONResponse(content=response_data.model_dump(mode="json"))
    _set_session_cookie(
        response,
        request,
        token=token,
        session_lifetime_hours=login_result.session_lifetime_hours,
    )
    return response


async def authenticate_login_request(
    request: Request,
    body: LoginRequest,
    session: DbSession,
) -> AuthenticatedLogin:
    """Authenticate a login request and record rate-limit/audit side effects."""
    auth_config = await load_system_config_values(session, ("session_lifetime_hours",))
    session_lifetime_hours = get_int_setting(auth_config, "session_lifetime_hours", 24)
    ip = request.client.host if request.client else "unknown"
    try:
        await _rate_limiter.check_rate_limit(ip)
    except LoginRateLimitError:
        await _audit(
            session,
            AuditEventType.LOGIN_RATE_LIMITED,
            use_dedicated_session=True,
            source_ip=ip,
            username=body.username,
            detail=f"Rate-limited login attempt from {ip}",
        )
        raise

    try:
        user = await AuthService.authenticate(session, body.username, body.password)
    except AuthenticationError:
        await _rate_limiter.record_failure(ip)
        await _audit(
            session,
            AuditEventType.LOGIN_FAILURE,
            source_ip=ip,
            username=body.username,
            detail=f"Failed login attempt for '{body.username}'",
        )
        raise

    await _rate_limiter.record_success(ip)
    user_id = user.id
    username = user.username
    is_active = user.is_active
    session_version = user.session_version
    login_result = AuthenticatedLogin(
        user_id=user_id,
        username=username,
        is_active=is_active,
        session_version=session_version,
        session_lifetime_hours=session_lifetime_hours,
    )
    await _audit(
        session,
        AuditEventType.LOGIN_SUCCESS,
        source_ip=ip,
        user_id=user_id,
        username=username,
        detail=f"User '{username}' logged in",
    )
    return login_result


@router.post("/auth/login", response_model=LoginResponse)
async def login(
    request: Request,
    body: LoginRequest,
    session: DbSession,
) -> JSONResponse:
    """Authenticate with username and password. Sets a session cookie."""
    login_result = await authenticate_login_request(request, body, session)
    return _build_login_session_response(login_result, request)


@router.post("/auth/logout")
async def logout(request: Request) -> JSONResponse:
    """Clear the session cookie."""
    response = JSONResponse(content={"message": "Logged out."})
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        httponly=True,
        samesite="lax",
        secure=is_secure_request(request),
        path="/",
    )
    return response


@router.get("/auth/password-policy", response_model=PasswordPolicyResponse)
async def get_password_policy() -> PasswordPolicyResponse:
    """Return the current password policy requirements.

    This is a public endpoint (no auth required) so the login/setup
    pages can display policy requirements. It only exposes the RULES,
    not any user data.
    """
    from pullbox.core.password_policy import (
        MAX_PASSWORD_BYTES,
        MAX_PASSWORD_LENGTH,
        MIN_PASSWORD_LENGTH,
    )

    return PasswordPolicyResponse(
        min_length=MIN_PASSWORD_LENGTH,
        max_length=MAX_PASSWORD_LENGTH,
        max_bytes=MAX_PASSWORD_BYTES,
        requirements=[
            PolicyRequirement(
                id="min_length",
                label=f"At least {MIN_PASSWORD_LENGTH} characters",
                type="length",
            ),
            PolicyRequirement(
                id="max_length",
                label=f"At most {MAX_PASSWORD_LENGTH} characters",
                type="length",
            ),
            PolicyRequirement(
                id="max_bytes",
                label=f"At most {MAX_PASSWORD_BYTES} UTF-8 bytes",
                type="length",
            ),
            PolicyRequirement(
                id="uppercase",
                label="One uppercase letter (A\u2013Z)",
                type="character",
            ),
            PolicyRequirement(
                id="lowercase",
                label="One lowercase letter (a\u2013z)",
                type="character",
            ),
            PolicyRequirement(
                id="digit",
                label="One digit (0\u20139)",
                type="character",
            ),
            PolicyRequirement(
                id="special",
                label="One special character (!@#$%...)",
                type="character",
            ),
        ],
    )


@router.get("/auth/apikeys", response_model=list[APIKeyResponse], include_in_schema=False)
async def list_api_keys(
    user: InteractiveOperatorUser,
    session: DbSession,
) -> list[APIKey]:
    """List the authenticated user's active API keys."""
    result = await session.execute(
        select(APIKey).where(
            APIKey.user_id == user.id,
            APIKey.is_active.is_(True),
        )
    )
    return list(result.scalars().all())


@router.post(
    "/auth/apikeys",
    response_model=APIKeyCreatedResponse,
    status_code=201,
    include_in_schema=False,
)
async def create_api_key(
    request: Request,
    body: APIKeyCreate,
    user: InteractiveOperatorUser,
    session: DbSession,
) -> APIKeyCreatedResponse:
    """Generate a new API key. The raw key is returned only once."""
    raw_key, api_key = await AuthService.generate_api_key(
        session, user.id, body.name, body.expires_at
    )
    await _audit(
        session,
        AuditEventType.API_KEY_CREATED,
        source_ip=source_ip_from_request(request),
        user_id=user.id,
        username=user.username,
        detail=f"API key '{body.name}' created",
    )
    return APIKeyCreatedResponse(
        key=raw_key,
        api_key=APIKeyResponse.model_validate(api_key),
    )


@router.delete("/auth/apikeys/{key_id}", status_code=204, include_in_schema=False)
async def deactivate_api_key(
    request: Request,
    key_id: int,
    user: InteractiveOperatorUser,
    session: DbSession,
) -> None:
    """Soft-deactivate an API key owned by the authenticated user."""
    result = await session.execute(
        select(APIKey).where(
            APIKey.id == key_id,
            APIKey.user_id == user.id,
            APIKey.is_active.is_(True),
        )
    )
    api_key = result.scalar_one_or_none()
    if api_key is None:
        from pullbox.core.exceptions import NotFoundError

        raise NotFoundError("APIKey", key_id)

    api_key.is_active = False
    await _audit(
        session,
        AuditEventType.API_KEY_REVOKED,
        source_ip=source_ip_from_request(request),
        user_id=user.id,
        username=user.username,
        detail=f"API key '{api_key.name}' revoked",
    )
    logger.info("api_key_deactivated", key_id=key_id, user_id=user.id)


@router.put("/auth/account", response_model=AccountUpdateResponse, include_in_schema=False)
async def update_account(
    request: Request,
    body: AccountUpdateRequest,
    user: InteractiveOperatorUser,
    session: DbSession,
) -> AccountUpdateResponse | JSONResponse:
    """Update the authenticated user's username and/or password.

    Requires current password for verification. If new_password is
    provided, confirm_password must match. Password changes invalidate
    all existing sessions and return a fresh session cookie.
    """
    # Verify current password
    if not AuthService.verify_password(body.current_password, user.password_hash):
        raise AuthenticationError("Current password is incorrect.")

    # Validate: at least one change requested
    if not body.new_username and not body.new_password:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="No changes requested.")

    username_changed = False
    password_changed = False

    # Update username
    if body.new_username and body.new_username != user.username:
        from pullbox.core.password_policy import validate_username

        un_violations = validate_username(body.new_username)
        if un_violations:
            from pullbox.core.exceptions import ValidationError

            raise ValidationError("; ".join(un_violations), details={"violations": un_violations})
        # Check uniqueness
        existing = await session.execute(
            select(User).where(User.username == body.new_username, User.id != user.id)
        )
        if existing.scalar_one_or_none():
            from fastapi import HTTPException

            raise HTTPException(status_code=409, detail="Username already taken.")
        user.username = body.new_username
        username_changed = True
        logger.info("username_changed", user_id=user.id, new_username=body.new_username)

    # Update password — also invalidates all existing sessions
    if body.new_password:
        if body.new_password != body.confirm_password:
            from fastapi import HTTPException

            raise HTTPException(
                status_code=400, detail="New password and confirmation do not match."
            )
        from pullbox.core.password_policy import validate_password

        pw_violations = validate_password(body.new_password)
        if pw_violations:
            from pullbox.core.exceptions import ValidationError

            raise ValidationError("; ".join(pw_violations), details={"violations": pw_violations})
        user.password_hash = AuthService.hash_password(body.new_password)
        password_changed = True
        logger.info("password_changed", user_id=user.id)

    await session.flush()

    if username_changed:
        await _audit(
            session,
            AuditEventType.USERNAME_CHANGED,
            source_ip=source_ip_from_request(request),
            user_id=user.id,
            username=user.username,
            detail=f"Username changed to '{body.new_username}'",
        )
    if password_changed:
        await _audit(
            session,
            AuditEventType.PASSWORD_CHANGED,
            source_ip=source_ip_from_request(request),
            user_id=user.id,
            username=user.username,
            detail="Password changed",
        )

    # Invalidate all sessions on any credential change (username or password)
    reason_parts: list[str] = []
    if username_changed:
        reason_parts.append("username change")
    if password_changed:
        reason_parts.append("password change")

    await AuthService.increment_session_version(session, user.id)
    await _audit(
        session,
        AuditEventType.SESSION_INVALIDATED,
        source_ip=source_ip_from_request(request),
        user_id=user.id,
        username=user.username,
        detail=f"All sessions invalidated ({', '.join(reason_parts)})",
    )

    # Build response message
    parts: list[str] = []
    if username_changed:
        parts.append("Username updated")
    if password_changed:
        parts.append("Password updated")
    parts.append("Please log in again")

    # Clear the session cookie — forces re-login with new credentials
    response_data = AccountUpdateResponse(
        message=". ".join(parts) + ".",
        username_changed=username_changed,
        password_changed=password_changed,
    )
    response = JSONResponse(content=response_data.model_dump(mode="json"))
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        httponly=True,
        samesite="lax",
        secure=is_secure_request(request),
        path="/",
    )
    return response


@router.post("/system/setup", response_model=SetupAccountCreatedResponse, status_code=201)
async def setup(
    body: SetupRequest,
    session: DbSession,
) -> JSONResponse:
    """Create the first admin user during initial setup.

    Only works when no users exist. Setup is considered complete once the
    account exists, and the user must continue through the normal login page.
    """
    has_users = await AuthService.has_users(session)
    if has_users:
        raise AuthenticationError("Setup has already been completed.")

    user = await AuthService.create_user(session, body.username, body.password)
    mark_setup_complete()
    logger.info("setup_account_created", username=user.username)
    return JSONResponse(
        status_code=201,
        content=SetupAccountCreatedResponse(message="Account created. Please log in.").model_dump(
            mode="json"
        ),
    )
