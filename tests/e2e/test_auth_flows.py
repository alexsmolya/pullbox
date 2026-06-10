"""
Authentication flow E2E tests — setup wizard, login, session management.

Tests multi-step auth flows that can't be validated by unit tests alone:
cookie behavior, redirect chains, CSRF, rate limiting, and session persistence.

Run:
    pytest tests/e2e/test_auth_flows.py -v --browser chromium
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

from tests.e2e.pages.login import LoginPage
from tests.e2e.pages.setup_wizard import SetupWizardPage

pytestmark = pytest.mark.e2e


class TestLoginFlow:
    """Login form behavior — valid/invalid credentials, error display."""

    def test_login_with_valid_credentials(self, page, seeded_server: str) -> None:  # type: ignore[no-untyped-def]
        """Successful login redirects to dashboard."""
        lp = LoginPage(page, seeded_server)
        lp.login("admin", "TestPassword1!")
        page.wait_for_url("**/", timeout=5000)
        assert "/login" not in page.url
        assert "/setup" not in page.url

    def test_login_with_invalid_password(self, page, seeded_server: str) -> None:  # type: ignore[no-untyped-def]
        """Invalid password shows error, stays on login page."""
        lp = LoginPage(page, seeded_server)
        lp.login("admin", "wrongpassword")
        # Wait for error to appear
        page.wait_for_selector("#login-error:not(.hidden)", timeout=3000)
        assert "/login" in page.url
        error = lp.get_error_message()
        assert error is not None

    def test_login_with_nonexistent_user(self, page, seeded_server: str) -> None:  # type: ignore[no-untyped-def]
        """Nonexistent user shows generic error (no user enumeration)."""
        lp = LoginPage(page, seeded_server)
        lp.login("nobody", "TestPassword1!")
        page.wait_for_selector("#login-error:not(.hidden)", timeout=3000)
        error = lp.get_error_message()
        assert error is not None
        # Error should NOT reveal whether user exists
        assert "nobody" not in (error or "").lower()

    def test_login_form_has_required_fields(self, page, seeded_server: str) -> None:  # type: ignore[no-untyped-def]
        """Login form has username and password inputs with required attribute."""
        lp = LoginPage(page, seeded_server)
        lp.goto()
        username = page.get_by_test_id("login-username")
        password = page.get_by_test_id("login-password")
        assert (
            username.get_attribute("required") is not None
            or username.get_attribute("required") == ""
        )
        assert (
            password.get_attribute("required") is not None
            or password.get_attribute("required") == ""
        )

    def test_first_login_prompts_for_usage_stats_once(
        self,
        page,
        first_run_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        """First sign-in should show the one-time usage stats prompt and never repeat after choice."""
        setup = SetupWizardPage(page, first_run_server)
        setup.goto()
        setup.fill_username("admin")
        setup.fill_password("Password@1")
        setup.fill_confirm_password("Password@1")
        setup.submit_account()

        page.wait_for_url(f"{first_run_server}/login", timeout=5000)

        login = LoginPage(page, first_run_server)
        login.fill_username("admin")
        login.fill_password("Password@1")
        login.submit()

        page.wait_for_url(f"{first_run_server}/", timeout=5000)
        modal = page.get_by_test_id("usage-stats-modal")
        expect(modal).to_be_visible()

        page.get_by_test_id("usage-stats-modal-disable").click()
        expect(modal).to_be_hidden()

        page.reload()
        expect(page.get_by_test_id("usage-stats-modal")).to_be_hidden()


class TestSessionManagement:
    """Session cookie persistence, logout, and protected route access."""

    def test_authenticated_user_can_access_series(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        """Session cookie grants access to protected routes."""
        authed_page.goto(f"{seeded_server}/series")
        assert "/login" not in authed_page.url
        assert "/setup" not in authed_page.url
        # Should see the series page content
        assert "Series" in authed_page.title() or authed_page.locator("text=Series").count() > 0

    def test_unauthenticated_redirect_to_login(self, page, seeded_server: str) -> None:  # type: ignore[no-untyped-def]
        """Unauthenticated request to protected route redirects to login."""
        page.goto(f"{seeded_server}/series")
        page.wait_for_url("**/login**", timeout=5000)
        assert "/login" in page.url

    def test_logout_clears_session(self, page, seeded_server: str) -> None:  # type: ignore[no-untyped-def]
        """After logout, accessing protected routes redirects to login."""
        # Login first
        lp = LoginPage(page, seeded_server)
        lp.login("admin", "TestPassword1!")
        page.wait_for_url("**/", timeout=5000)
        assert "/login" not in page.url

        # Logout via POST to /logout
        page.goto(f"{seeded_server}/logout")
        page.wait_for_url("**/login**", timeout=5000)

        # Verify session is cleared — accessing /series should redirect to login
        page.goto(f"{seeded_server}/series")
        page.wait_for_url("**/login**", timeout=5000)
        assert "/login" in page.url

    def test_session_cookie_is_httponly(self, page, seeded_server: str) -> None:  # type: ignore[no-untyped-def]
        """Session cookie has HttpOnly flag (not accessible via JavaScript)."""
        import httpx

        resp = httpx.post(
            f"{seeded_server}/api/v1/auth/login",
            json={"username": "admin", "password": "TestPassword1!"},
            timeout=5.0,
        )
        assert resp.status_code == 200
        # Check cookie attributes from the Set-Cookie header
        set_cookie = resp.headers.get("set-cookie", "")
        assert "httponly" in set_cookie.lower()

    def test_expired_session_fetch_redirects_to_login_without_toasts(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        """Expired fetch requests should redirect cleanly back to the login page."""
        authed_page.goto(f"{seeded_server}/series")
        authed_page.wait_for_load_state("networkidle")

        authed_page.evaluate(
            """() => {
                sessionStorage.setItem("__pbAuthRedirectToasts", "[]");
                if (window.__pbToastSpyInstalled) {
                    return;
                }
                window.__pbToastSpyInstalled = true;
                var originalShowToast = window.showToast;
                window.showToast = function(detail) {
                    var existing = JSON.parse(
                        sessionStorage.getItem("__pbAuthRedirectToasts") || "[]"
                    );
                    existing.push(detail && detail.message ? detail.message : "");
                    sessionStorage.setItem("__pbAuthRedirectToasts", JSON.stringify(existing));
                    return originalShowToast.apply(this, arguments);
                };
            }"""
        )

        authed_page.context.clear_cookies()
        authed_page.evaluate(
            """() => {
                fetch("/api/v1/system/backups", { credentials: "same-origin" }).catch(function () {
                    return null;
                });
            }"""
        )

        expect(authed_page).to_have_url(re.compile(r".*/login(?:\\?.*)?$"), timeout=5000)
        toast_messages = authed_page.evaluate(
            '() => JSON.parse(sessionStorage.getItem("__pbAuthRedirectToasts") || "[]")'
        )
        assert toast_messages == []

    def test_expired_session_htmx_redirects_to_login_without_toasts(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        """Expired HTMX requests should redirect cleanly back to the login page."""
        authed_page.goto(f"{seeded_server}/series")
        authed_page.wait_for_load_state("networkidle")

        authed_page.evaluate(
            """() => {
                sessionStorage.setItem("__pbAuthRedirectToasts", "[]");
                if (window.__pbToastSpyInstalled) {
                    return;
                }
                window.__pbToastSpyInstalled = true;
                var originalShowToast = window.showToast;
                window.showToast = function(detail) {
                    var existing = JSON.parse(
                        sessionStorage.getItem("__pbAuthRedirectToasts") || "[]"
                    );
                    existing.push(detail && detail.message ? detail.message : "");
                    sessionStorage.setItem("__pbAuthRedirectToasts", JSON.stringify(existing));
                    return originalShowToast.apply(this, arguments);
                };
            }"""
        )

        authed_page.context.clear_cookies()
        authed_page.evaluate(
            """() => {
                htmx.ajax("GET", "/htmx/dashboard/briefing", {
                    target: "#content",
                    swap: "innerHTML",
                });
            }"""
        )

        expect(authed_page).to_have_url(re.compile(r".*/login(?:\\?.*)?$"), timeout=5000)
        toast_messages = authed_page.evaluate(
            '() => JSON.parse(sessionStorage.getItem("__pbAuthRedirectToasts") || "[]")'
        )
        assert toast_messages == []
