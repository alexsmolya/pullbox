"""Route-contract tests for auth-expiry redirect behavior."""

from __future__ import annotations

import os
import sys

import pytest

from pullbox.app import AUTH_REDIRECT_HEADER, AUTH_REDIRECT_PATH

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

pytest_plugins = ["conftest_security"]

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-auth-redirect-ui")


@pytest.mark.asyncio
class TestAuthRedirectContract:
    """Protected routes should distinguish page loads from XHR/HTMX auth failures."""

    async def test_full_page_navigation_redirects_to_login(
        self,
        unauthenticated_client,
        sec_user,
    ) -> None:  # type: ignore[no-untyped-def]
        response = await unauthenticated_client.get(
            "/series",
            headers={"Accept": "text/html"},
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert response.headers["location"] == AUTH_REDIRECT_PATH
        assert AUTH_REDIRECT_HEADER not in response.headers

    async def test_htmx_request_returns_401_with_auth_redirect_header(
        self,
        unauthenticated_client,
        sec_user,
    ) -> None:  # type: ignore[no-untyped-def]
        response = await unauthenticated_client.get(
            "/htmx/dashboard/briefing",
            headers={"HX-Request": "true", "Accept": "text/html"},
            follow_redirects=False,
        )

        assert response.status_code == 401
        assert response.headers[AUTH_REDIRECT_HEADER] == AUTH_REDIRECT_PATH
        assert response.json()["error"]["code"] == "AUTH_REQUIRED"

    async def test_api_request_returns_401_with_auth_redirect_header(
        self,
        unauthenticated_client,
        sec_user,
    ) -> None:  # type: ignore[no-untyped-def]
        response = await unauthenticated_client.get(
            "/api/v1/system/backups",
            follow_redirects=False,
        )

        assert response.status_code == 401
        assert response.headers[AUTH_REDIRECT_HEADER] == AUTH_REDIRECT_PATH
        assert response.json()["error"]["code"] == "AUTH_REQUIRED"
