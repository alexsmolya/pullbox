"""Focused browser coverage for the standalone login shell."""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from tests.e2e.pages.login import LoginPage

pytestmark = pytest.mark.e2e


class TestLoginPage:
    """Behavior-first E2E checks for the setup-matched login shell."""

    def test_login_page_renders_setup_matched_shell(
        self,
        page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        login = LoginPage(page, seeded_server)
        login.goto()

        assert login.page_root.is_visible()
        assert login.hero.is_visible()
        assert login.desktop_brand.is_visible()
        assert login.card.is_visible()
        assert login.form.is_visible()
        assert login.username_input.is_visible()
        assert login.password_input.is_visible()
        assert login.submit_button.is_visible()
        expect(page.get_by_text("Sign in to keep your collection moving.")).to_be_visible()

    def test_login_page_avoids_framework_asset_requests(
        self,
        page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        framework_requests: list[str] = []

        def _capture_request(request) -> None:  # type: ignore[no-untyped-def]
            url = request.url
            if any(
                asset in url
                for asset in (
                    "/static/css/tailwind.css",
                    "/static/js/alpine.min.js",
                    "/static/js/pullbox.js",
                )
            ):
                framework_requests.append(url)

        page.on("request", _capture_request)

        login = LoginPage(page, seeded_server)
        login.goto()

        assert framework_requests == []

    def test_login_page_keeps_shell_visible_on_invalid_credentials(
        self,
        page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        login = LoginPage(page, seeded_server)
        login.goto()
        login.fill_username("admin")
        login.fill_password("wrongpassword")
        login.submit()

        login.error_banner.wait_for(state="visible", timeout=3000)
        assert login.page_root.is_visible()
        assert login.card.is_visible()
        assert "/login" in page.url
