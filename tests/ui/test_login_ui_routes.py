"""Route-contract tests for the standalone login page."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

pytest_plugins = ["conftest_security"]

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-login-ui")


@pytest.mark.asyncio
class TestLoginRouteContracts:
    """Verify login uses the same lean shell contract as setup."""

    async def test_login_renders_setup_matched_standalone_shell(
        self,
        unauthenticated_client,
    ) -> None:  # type: ignore[no-untyped-def]
        response = await unauthenticated_client.get("/login")

        assert response.status_code == 200
        assert 'data-testid="login-page"' in response.text
        assert 'data-testid="login-shell"' in response.text
        assert 'data-testid="login-card"' in response.text
        assert 'data-testid="login-form"' in response.text
        assert 'method="post"' in response.text
        assert 'action="/login"' in response.text
        assert 'data-testid="login-username"' in response.text
        assert 'data-testid="login-password"' in response.text
        assert 'data-testid="login-submit"' in response.text
        assert 'data-testid="login-hero"' in response.text
        assert 'data-testid="login-side-panel"' in response.text
        assert 'id="login-critical-shell"' in response.text
        assert 'class="setup-brand"' in response.text
        assert 'class="setup-brand-wordmark"' in response.text
        assert 'aria-label="Pullbox"' in response.text
        assert 'rel="stylesheet"' not in response.text
        assert "/static/css/tailwind.css" not in response.text
        assert "/static/js/alpine.min.js" not in response.text
        assert "/static/js/pullbox.js" not in response.text
        assert 'rel="preload" href="/static/fonts/' not in response.text
        assert 'data-standalone-shell-version="' in response.text
        assert "__pbValidateStandaloneShellFreshness" not in response.text
        assert "preventStandaloneDocumentRestore" not in response.text
        assert 'x-data="loginPage()"' not in response.text
        assert "font-family: var(--setup-sans);" in response.text
        assert "--setup-sans: ui-sans-serif, system-ui" in response.text

    async def test_login_matches_setup_shell_copy_contract(
        self,
        unauthenticated_client,
    ) -> None:  # type: ignore[no-untyped-def]
        response = await unauthenticated_client.get("/login")

        assert response.status_code == 200
        assert "Your library, your rules" in response.text
        assert "Sign in to keep your collection moving." in response.text
        assert (
            "Search, downloads, imports, and cleanup stay close so new issues "
            "land without juggling tabs and tools."
        ) in response.text
        assert "Sign in" in response.text
        assert "Sign in with the account you created during setup." in response.text
        assert "Access your library." not in response.text
        assert "If you have not created an account yet" not in response.text
        assert "Instance online" in response.text
        assert "Self-hosted" in response.text
        assert "Private access" in response.text

    async def test_login_redirects_authenticated_users_to_dashboard(
        self,
        authenticated_client,
    ) -> None:  # type: ignore[no-untyped-def]
        response = await authenticated_client.get("/login", follow_redirects=False)

        assert response.status_code == 302
        assert response.headers["location"] == "/"

    async def test_login_form_post_sets_session_cookie_and_redirects(
        self,
        unauthenticated_client,
        sec_user,
    ) -> None:  # type: ignore[no-untyped-def]
        response = await unauthenticated_client.post(
            "/login",
            data={"username": sec_user.username, "password": "Test@1234"},
            headers={"accept": "text/html"},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == "/"
        assert "pullbox_session=" in response.headers["set-cookie"]

    async def test_login_form_post_rerenders_shell_with_error(
        self,
        unauthenticated_client,
        sec_user,
    ) -> None:  # type: ignore[no-untyped-def]
        response = await unauthenticated_client.post(
            "/login",
            data={"username": sec_user.username, "password": "wrong"},
            headers={"accept": "text/html"},
            follow_redirects=False,
        )

        assert response.status_code == 401
        assert 'data-testid="login-page"' in response.text
        assert 'data-testid="login-error"' in response.text
        assert "Invalid username or password." in response.text
        assert f'value="{sec_user.username}"' in response.text
        assert "pullbox_session=" not in response.headers.get("set-cookie", "")
