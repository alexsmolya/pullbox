"""Unit tests for session cookie security flags.

Tests verify that login responses set httponly, samesite, secure, and
path flags correctly on session cookies.

Run:
    pytest tests/unit/test_cookie_flags.py -v
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-cookie-flags")

from pullbox.config import PullboxSettings
from pullbox.services.auth_service import SESSION_COOKIE_NAME

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


def _make_settings(*, debug: bool) -> PullboxSettings:
    return PullboxSettings(secret_key="test-secret", debug=debug)  # type: ignore[call-arg]


def _build_cookie_app(*, debug: bool, session_lifetime_hours: int = 24) -> FastAPI:
    """Build a minimal app that sets a session cookie like auth.py does."""
    from pullbox.api.v1.auth import _build_session_response

    app = FastAPI()
    _make_settings(debug=debug)

    mock_user = MagicMock()
    mock_user.id = 1
    mock_user.username = "admin"
    mock_user.is_active = True
    mock_user.session_version = 0

    @app.get("/test/login")
    async def fake_login(request: Request):  # type: ignore[no-untyped-def]
        return _build_session_response(
            mock_user,
            request,
            session_lifetime_hours=session_lifetime_hours,
            session_version=0,
        )

    return app


@pytest.fixture
async def prod_client() -> AsyncGenerator[AsyncClient, None]:
    app = _build_cookie_app(debug=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def debug_client() -> AsyncGenerator[AsyncClient, None]:
    app = _build_cookie_app(debug=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def _get_session_cookie_header(response) -> str:  # type: ignore[no-untyped-def]
    """Extract the raw Set-Cookie header for the session cookie."""
    for key, val in response.headers.multi_items():
        if key.lower() == "set-cookie" and SESSION_COOKIE_NAME in val:
            return val
    return ""


class TestCookieFlags:
    """Tests for session cookie security flags."""

    @pytest.mark.asyncio
    async def test_login_sets_httponly_cookie(self, prod_client: AsyncClient) -> None:
        resp = await prod_client.get("/test/login")
        cookie = _get_session_cookie_header(resp)
        assert "httponly" in cookie.lower()

    @pytest.mark.asyncio
    async def test_login_sets_samesite_cookie(self, prod_client: AsyncClient) -> None:
        resp = await prod_client.get("/test/login")
        cookie = _get_session_cookie_header(resp)
        assert "samesite=lax" in cookie.lower()

    @pytest.mark.asyncio
    async def test_login_no_secure_on_http(self, prod_client: AsyncClient) -> None:
        """HTTP requests should NOT set the Secure flag, even in production."""
        resp = await prod_client.get("/test/login")
        cookie = _get_session_cookie_header(resp)
        assert "secure" not in cookie.lower()

    @pytest.mark.asyncio
    async def test_login_ignores_forwarded_proto_from_untrusted_proxy(
        self, prod_client: AsyncClient
    ) -> None:
        """Untrusted X-Forwarded-Proto should not force Secure cookies."""
        resp = await prod_client.get("/test/login", headers={"X-Forwarded-Proto": "https"})
        cookie = _get_session_cookie_header(resp)
        assert "secure" not in cookie.lower()

    @pytest.mark.asyncio
    async def test_login_secure_with_trusted_forwarded_proto(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Trusted reverse proxy HTTPS should set Secure cookies."""
        monkeypatch.setenv("PULLBOX_TRUSTED_PROXIES", "127.0.0.1")
        from pullbox.config import get_settings

        get_settings.cache_clear()
        try:
            app = _build_cookie_app(debug=False)
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    "/test/login",
                    headers={"X-Forwarded-Proto": "https"},
                )
        finally:
            get_settings.cache_clear()

        cookie = _get_session_cookie_header(resp)
        assert "secure" in cookie.lower()

    @pytest.mark.asyncio
    async def test_login_no_secure_in_debug(self, debug_client: AsyncClient) -> None:
        resp = await debug_client.get("/test/login")
        cookie = _get_session_cookie_header(resp)
        assert "secure" not in cookie.lower()

    @pytest.mark.asyncio
    async def test_login_sets_path_cookie(self, prod_client: AsyncClient) -> None:
        resp = await prod_client.get("/test/login")
        cookie = _get_session_cookie_header(resp)
        assert "path=/" in cookie.lower()

    @pytest.mark.asyncio
    async def test_login_sets_cookie_max_age_from_session_lifetime(self) -> None:
        app = _build_cookie_app(debug=False, session_lifetime_hours=3)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/test/login")

        cookie = _get_session_cookie_header(resp)
        assert "max-age=10800" in cookie.lower()
