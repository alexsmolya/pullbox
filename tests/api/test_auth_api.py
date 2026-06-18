"""Direct route-function coverage for authentication API contracts."""

from __future__ import annotations

import hashlib
import os
import sys
from typing import TYPE_CHECKING

import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from starlette.requests import Request

from pullbox.api.v1 import auth as auth_api
from pullbox.core.exceptions import (
    AuthenticationError,
    LoginRateLimitError,
    NotFoundError,
    ValidationError,
)
from pullbox.models.user import APIKey, User
from pullbox.schemas.auth import AccountUpdateRequest, APIKeyCreate, LoginRequest, SetupRequest
from pullbox.services.auth_service import SESSION_COOKIE_NAME, AuthService

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytest_plugins = ["conftest_security"]


def _request(
    *,
    method: str = "POST",
    path: str = "/api/v1/auth/login",
    scheme: str = "http",
    host: str = "127.0.0.1",
) -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "scheme": scheme,
            "client": (host, 443 if scheme == "https" else 80),
            "headers": [],
        }
    )


async def _create_user(
    session: AsyncSession,
    *,
    username: str = "admin",
    password: str = "Password@1",
) -> User:
    user = User(
        username=username,
        password_hash=AuthService.hash_password(password),
    )
    session.add(user)
    await session.flush()
    return user


class _FakeRateLimiter:
    def __init__(self, *, limited: bool = False) -> None:
        self.limited = limited
        self.failures = 0
        self.successes = 0

    async def check_rate_limit(self, _ip: str) -> None:
        if self.limited:
            raise LoginRateLimitError(60, "Too many login attempts.")

    async def record_failure(self, _ip: str) -> None:
        self.failures += 1

    async def record_success(self, _ip: str) -> None:
        self.successes += 1


@pytest.fixture(autouse=True)
def _patch_auth_side_effects(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    audit_calls: list[dict[str, object]] = []

    async def _audit_stub(*args: object, **kwargs: object) -> None:
        audit_calls.append({"args": args, "kwargs": kwargs})

    monkeypatch.setattr(auth_api, "_audit", _audit_stub)
    monkeypatch.setattr(auth_api, "_rate_limiter", _FakeRateLimiter())
    return audit_calls


@pytest.mark.asyncio
class TestLoginAndSessionRoutes:
    async def test_session_response_helpers_attach_cookie_and_csrf(
        self,
        sec_db: async_sessionmaker[AsyncSession],
    ) -> None:
        async with sec_db() as session:
            user = await _create_user(session)

            response = JSONResponse(content={"ok": True})
            csrf = auth_api.attach_session_cookie(
                response,
                user.id,
                _request(scheme="https"),
                session_lifetime_hours=12,
                session_version=user.session_version,
            )
            assert csrf
            assert f"{SESSION_COOKIE_NAME}=" in response.headers["set-cookie"]
            assert "Max-Age=43200" in response.headers["set-cookie"]

            session_response = auth_api._build_session_response(
                user,
                _request(),
                session_lifetime_hours=24,
                session_version=user.session_version,
            )
            assert session_response.status_code == 200
            assert f"{SESSION_COOKIE_NAME}=" in session_response.headers["set-cookie"]

    async def test_login_authenticates_records_success_and_sets_session_cookie(
        self,
        sec_db: async_sessionmaker[AsyncSession],
        _patch_auth_side_effects: list[dict[str, object]],
    ) -> None:
        async with sec_db() as session:
            user = await _create_user(session)

            response = await auth_api.login(
                _request(),
                LoginRequest(username=user.username, password="Password@1"),
                session,
            )

        assert response.status_code == 200
        assert response.headers["set-cookie"].startswith(f"{SESSION_COOKIE_NAME}=")
        assert response.body
        assert _patch_auth_side_effects[-1]["kwargs"]["username"] == "admin"
        assert auth_api._rate_limiter.successes == 1

    async def test_authenticate_login_records_failure_and_rate_limit(
        self,
        sec_db: async_sessionmaker[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async with sec_db() as session:
            await _create_user(session)

            with pytest.raises(AuthenticationError):
                await auth_api.authenticate_login_request(
                    _request(),
                    LoginRequest(username="admin", password="wrong-password"),
                    session,
                )
            assert auth_api._rate_limiter.failures == 1

            monkeypatch.setattr(auth_api, "_rate_limiter", _FakeRateLimiter(limited=True))
            with pytest.raises(LoginRateLimitError):
                await auth_api.authenticate_login_request(
                    _request(),
                    LoginRequest(username="admin", password="Password@1"),
                    session,
                )

    async def test_logout_clears_session_cookie(self) -> None:
        response = await auth_api.logout(_request(path="/api/v1/auth/logout"))

        assert response.status_code == 200
        assert response.headers["set-cookie"].startswith(f"{SESSION_COOKIE_NAME}=")
        assert "Max-Age=0" in response.headers["set-cookie"]


@pytest.mark.asyncio
class TestApiKeyRouteFunctions:
    async def test_api_key_lifecycle_is_scoped_to_active_user_keys(
        self,
        sec_db: async_sessionmaker[AsyncSession],
    ) -> None:
        async with sec_db() as session:
            user = await _create_user(session)
            other_user = await _create_user(session, username="other", password="Password@2")
            active_key = APIKey(
                user_id=user.id,
                key_hash=hashlib.sha256(b"active").hexdigest(),
                name="Active",
                is_active=True,
            )
            inactive_key = APIKey(
                user_id=user.id,
                key_hash=hashlib.sha256(b"inactive").hexdigest(),
                name="Inactive",
                is_active=False,
            )
            other_key = APIKey(
                user_id=other_user.id,
                key_hash=hashlib.sha256(b"other").hexdigest(),
                name="Other",
                is_active=True,
            )
            session.add_all([active_key, inactive_key, other_key])
            await session.flush()

            listed = await auth_api.list_api_keys(user, session)  # type: ignore[arg-type]
            assert [key.name for key in listed] == ["Active"]

            created = await auth_api.create_api_key(
                _request(path="/api/v1/auth/apikeys"),
                APIKeyCreate(name=" Created Key "),
                user,  # type: ignore[arg-type]
                session,
            )
            assert created.key.startswith("pb_k1_")
            assert created.api_key.name == "Created Key"

            await auth_api.deactivate_api_key(
                _request(method="DELETE", path="/api/v1/auth/apikeys/1"),
                active_key.id,
                user,  # type: ignore[arg-type]
                session,
            )
            await session.flush()
            await session.refresh(active_key)
            assert active_key.is_active is False

            with pytest.raises(NotFoundError):
                await auth_api.deactivate_api_key(
                    _request(method="DELETE", path="/api/v1/auth/apikeys/999"),
                    other_key.id,
                    user,  # type: ignore[arg-type]
                    session,
                )


@pytest.mark.asyncio
class TestAccountRouteFunction:
    async def test_rejects_invalid_account_update_requests(
        self,
        sec_db: async_sessionmaker[AsyncSession],
    ) -> None:
        async with sec_db() as session:
            user = await _create_user(session)
            await _create_user(session, username="taken", password="Password@2")

            with pytest.raises(AuthenticationError):
                await auth_api.update_account(
                    _request(method="PUT", path="/api/v1/auth/account"),
                    AccountUpdateRequest(current_password="wrong-password", new_username="new"),
                    user,  # type: ignore[arg-type]
                    session,
                )

            with pytest.raises(HTTPException) as no_changes:
                await auth_api.update_account(
                    _request(method="PUT", path="/api/v1/auth/account"),
                    AccountUpdateRequest(current_password="Password@1"),
                    user,  # type: ignore[arg-type]
                    session,
                )
            assert no_changes.value.status_code == 400

            with pytest.raises(HTTPException) as duplicate:
                await auth_api.update_account(
                    _request(method="PUT", path="/api/v1/auth/account"),
                    AccountUpdateRequest(current_password="Password@1", new_username="taken"),
                    user,  # type: ignore[arg-type]
                    session,
                )
            assert duplicate.value.status_code == 409

            with pytest.raises(ValidationError):
                await auth_api.update_account(
                    _request(method="PUT", path="/api/v1/auth/account"),
                    AccountUpdateRequest(current_password="Password@1", new_username="bad name"),
                    user,  # type: ignore[arg-type]
                    session,
                )

            with pytest.raises(HTTPException) as mismatch:
                await auth_api.update_account(
                    _request(method="PUT", path="/api/v1/auth/account"),
                    AccountUpdateRequest(
                        current_password="Password@1",
                        new_password="NewPassword@1",
                        confirm_password="Different@1",
                    ),
                    user,  # type: ignore[arg-type]
                    session,
                )
            assert mismatch.value.status_code == 400

            with pytest.raises(ValidationError):
                await auth_api.update_account(
                    _request(method="PUT", path="/api/v1/auth/account"),
                    AccountUpdateRequest(
                        current_password="Password@1",
                        new_password="weakpass",
                        confirm_password="weakpass",
                    ),
                    user,  # type: ignore[arg-type]
                    session,
                )

    async def test_updates_username_and_password_then_invalidates_session(
        self,
        sec_db: async_sessionmaker[AsyncSession],
    ) -> None:
        async with sec_db() as session:
            user = await _create_user(session)
            original_session_version = user.session_version

            response = await auth_api.update_account(
                _request(method="PUT", path="/api/v1/auth/account"),
                AccountUpdateRequest(
                    current_password="Password@1",
                    new_username="new-admin",
                    new_password="NewPassword@1",
                    confirm_password="NewPassword@1",
                ),
                user,  # type: ignore[arg-type]
                session,
            )

            await session.refresh(user)

        assert response.status_code == 200
        assert response.headers["set-cookie"].startswith(f"{SESSION_COOKIE_NAME}=")
        assert "Max-Age=0" in response.headers["set-cookie"]
        assert user.username == "new-admin"
        assert user.session_version == original_session_version + 1
        assert AuthService.verify_password("NewPassword@1", user.password_hash)
        assert response.body


@pytest.mark.asyncio
class TestSetupRouteFunction:
    async def test_setup_creates_first_user_and_rejects_completed_setup(
        self,
        sec_db: async_sessionmaker[AsyncSession],
    ) -> None:
        async with sec_db() as session:
            response = await auth_api.setup(
                SetupRequest(username="admin", password="Password@1"),
                session,
            )
            assert response.status_code == 201

            with pytest.raises(AuthenticationError):
                await auth_api.setup(
                    SetupRequest(username="other", password="Password@2"),
                    session,
                )
