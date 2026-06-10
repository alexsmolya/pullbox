"""Unit tests for CSRF enforcement middleware.

Tests verify that state-changing requests require a valid X-CSRF-Token
header, safe methods are exempt, and exempt paths bypass CSRF.

Run:
    pytest tests/unit/test_csrf.py -v
"""

from __future__ import annotations

import os
import secrets
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-csrf")

from pullbox.api.middleware import CsrfMiddleware
from pullbox.services.auth_service import SESSION_COOKIE_NAME, AuthService

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


def _build_csrf_app() -> FastAPI:
    """Build a minimal app with CsrfMiddleware for testing."""
    app = FastAPI()
    app.add_middleware(CsrfMiddleware)

    @app.get("/test/data")
    async def get_data() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/test/data")
    async def post_data() -> dict[str, str]:
        return {"status": "created"}

    @app.put("/test/data")
    async def put_data() -> dict[str, str]:
        return {"status": "updated"}

    @app.delete("/test/data")
    async def delete_data() -> dict[str, str]:
        return {"status": "deleted"}

    @app.post("/api/v1/auth/login")
    async def login() -> dict[str, str]:
        return {"status": "logged_in"}

    @app.post("/api/v1/auth/logout")
    async def api_logout() -> dict[str, str]:
        return {"status": "logged_out"}

    @app.post("/api/v1/system/setup")
    async def setup() -> dict[str, str]:
        return {"status": "setup_done"}

    @app.post("/logout")
    async def ui_logout() -> dict[str, str]:
        return {"status": "logged_out"}

    return app


def _create_session_with_csrf() -> tuple[str, str]:
    """Create a real session token and extract the CSRF token from it."""
    token = AuthService.create_session_token(user_id=1, session_version=0)
    csrf = AuthService.get_csrf_token_from_session(token)
    assert csrf is not None
    return token, csrf


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    app = _build_csrf_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestCsrfSafeMethods:
    """GET/HEAD/OPTIONS should skip CSRF validation."""

    @pytest.mark.asyncio
    async def test_get_request_skips_csrf(self, client: AsyncClient) -> None:
        resp = await client.get("/test/data")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_head_request_skips_csrf(self, client: AsyncClient) -> None:
        resp = await client.head("/test/data")
        # FastAPI returns 405 for HEAD on GET-only endpoints, but CSRF
        # middleware should not block it (no 403).
        assert resp.status_code != 403

    @pytest.mark.asyncio
    async def test_options_request_skips_csrf(self, client: AsyncClient) -> None:
        resp = await client.options("/test/data")
        # FastAPI returns 405 for OPTIONS on endpoints without explicit support,
        # but the CSRF middleware should not block it.
        assert resp.status_code != 403


class TestCsrfEnforcement:
    """State-changing requests with session cookies must include valid CSRF."""

    @pytest.mark.asyncio
    async def test_post_without_csrf_returns_403(self, client: AsyncClient) -> None:
        token, _csrf = _create_session_with_csrf()
        resp = await client.post(
            "/test/data",
            cookies={SESSION_COOKIE_NAME: token},
        )
        assert resp.status_code == 403
        assert "CSRF" in resp.json()["error"]["message"]

    @pytest.mark.asyncio
    async def test_post_with_valid_csrf_header_succeeds(self, client: AsyncClient) -> None:
        token, csrf = _create_session_with_csrf()
        resp = await client.post(
            "/test/data",
            cookies={SESSION_COOKIE_NAME: token},
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_post_with_invalid_csrf_returns_403(self, client: AsyncClient) -> None:
        token, _csrf = _create_session_with_csrf()
        resp = await client.post(
            "/test/data",
            cookies={SESSION_COOKIE_NAME: token},
            headers={"X-CSRF-Token": "wrong-token"},
        )
        assert resp.status_code == 403
        assert "invalid" in resp.json()["error"]["message"].lower()

    @pytest.mark.asyncio
    async def test_put_requires_csrf(self, client: AsyncClient) -> None:
        token, _csrf = _create_session_with_csrf()
        resp = await client.put(
            "/test/data",
            cookies={SESSION_COOKIE_NAME: token},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_delete_requires_csrf(self, client: AsyncClient) -> None:
        token, _csrf = _create_session_with_csrf()
        resp = await client.delete(
            "/test/data",
            cookies={SESSION_COOKIE_NAME: token},
        )
        assert resp.status_code == 403


class TestCsrfExemptions:
    """Certain paths and auth methods should bypass CSRF."""

    @pytest.mark.asyncio
    async def test_login_endpoint_exempt(self, client: AsyncClient) -> None:
        resp = await client.post("/api/v1/auth/login")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_setup_endpoint_exempt(self, client: AsyncClient) -> None:
        resp = await client.post("/api/v1/system/setup")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/auth/login",
            "/api/v1/auth/logout",
            "/api/v1/system/setup",
            "/logout",
        ],
    )
    async def test_cross_site_browser_posts_to_exempt_paths_return_403(
        self,
        client: AsyncClient,
        path: str,
    ) -> None:
        resp = await client.post(path, headers={"Sec-Fetch-Site": "cross-site"})

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "CSRF_ERROR"
        assert "Cross-site" in resp.json()["error"]["message"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("sec_fetch_site", ["same-origin", "same-site", "none"])
    async def test_same_site_browser_posts_to_exempt_paths_remain_allowed(
        self,
        client: AsyncClient,
        sec_fetch_site: str,
    ) -> None:
        resp = await client.post(
            "/api/v1/auth/login",
            headers={"Sec-Fetch-Site": sec_fetch_site},
        )

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_non_browser_posts_to_exempt_paths_remain_allowed(
        self,
        client: AsyncClient,
    ) -> None:
        resp = await client.post("/api/v1/auth/login")

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_api_key_auth_skips_csrf(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/test/data",
            headers={"x-api-key": "some-api-key"},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_api_key_header_does_not_bypass_session_csrf(self, client: AsyncClient) -> None:
        token, _csrf = _create_session_with_csrf()
        resp = await client.post(
            "/test/data",
            cookies={SESSION_COOKIE_NAME: token},
            headers={"x-api-key": "some-api-key"},
        )
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "CSRF_ERROR"

    @pytest.mark.asyncio
    async def test_no_session_cookie_passes_through(self, client: AsyncClient) -> None:
        # No session cookie = no CSRF to check, auth layer handles 401
        resp = await client.post("/test/data")
        assert resp.status_code == 200


class TestCsrfConstantTime:
    """Verify that constant-time comparison is used."""

    @pytest.mark.asyncio
    async def test_uses_constant_time_comparison(self, client: AsyncClient) -> None:
        token, csrf = _create_session_with_csrf()
        with patch(
            "pullbox.api.middleware.secrets.compare_digest",
            wraps=secrets.compare_digest,
        ) as mock_compare:
            await client.post(
                "/test/data",
                cookies={SESSION_COOKIE_NAME: token},
                headers={"X-CSRF-Token": csrf},
            )
            mock_compare.assert_called_once_with(csrf, csrf)
