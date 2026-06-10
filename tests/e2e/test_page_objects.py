"""
Unit tests for E2E Page Object Model classes.

Validates that POMs instantiate correctly, expose expected methods,
and interact with pages as expected.

Run:
    pytest tests/e2e/test_page_objects.py -v --browser chromium
"""

from __future__ import annotations

import pytest

from tests.e2e.pages.base import BasePage
from tests.e2e.pages.dashboard import DashboardPage
from tests.e2e.pages.health import HealthPage
from tests.e2e.pages.login import LoginPage
from tests.e2e.pages.series_list import SeriesListPage
from tests.e2e.pages.setup_wizard import SetupWizardPage

pytestmark = pytest.mark.e2e


class TestBasePageInstantiation:
    """Verify BasePage construction and core methods."""

    def test_base_page_instantiates(self, page, live_server: str) -> None:  # type: ignore[no-untyped-def]
        bp = BasePage(page, live_server)
        assert bp.page is page
        assert bp.base_url == live_server

    def test_navigate_loads_url(self, page, live_server: str) -> None:  # type: ignore[no-untyped-def]
        bp = BasePage(page, live_server)
        bp.navigate("/ping")
        assert "/ping" in page.url

    def test_wait_for_htmx_does_not_error(self, page, live_server: str) -> None:  # type: ignore[no-untyped-def]
        """wait_for_htmx returns without error on a simple page."""
        bp = BasePage(page, live_server)
        bp.navigate("/ping")
        bp.wait_for_htmx()


class TestLoginPage:
    """Verify LoginPage POM methods."""

    def test_login_page_instantiates(self, page, live_server: str) -> None:  # type: ignore[no-untyped-def]
        lp = LoginPage(page, live_server)
        assert lp.page is page

    def test_login_page_navigates_to_login(self, page, seeded_server: str) -> None:  # type: ignore[no-untyped-def]
        lp = LoginPage(page, seeded_server)
        lp.goto()
        assert "/login" in page.url

    def test_login_page_fills_and_submits(self, page, seeded_server: str) -> None:  # type: ignore[no-untyped-def]
        """Full login flow via POM: fill credentials, submit, verify redirect."""
        lp = LoginPage(page, seeded_server)
        lp.goto()
        lp.fill_username("admin")
        lp.fill_password("TestPassword1!")
        lp.submit()
        # Should redirect to dashboard after login
        page.wait_for_url("**/", timeout=5000)
        assert "/login" not in page.url


class TestSetupWizardPage:
    """Verify SetupWizardPage POM has expected account-form methods."""

    def test_setup_wizard_instantiates(self, page, live_server: str) -> None:  # type: ignore[no-untyped-def]
        sw = SetupWizardPage(page, live_server)
        assert sw.page is page

    def test_setup_wizard_has_account_methods(self, page, live_server: str) -> None:  # type: ignore[no-untyped-def]
        """SetupWizardPage exposes helpers for the single-page account flow."""
        sw = SetupWizardPage(page, live_server)
        assert callable(sw.goto)
        assert callable(sw.fill_username)
        assert callable(sw.fill_password)
        assert callable(sw.fill_confirm_password)
        assert callable(sw.submit_account)


class TestDashboardPage:
    """Verify DashboardPage POM methods."""

    def test_dashboard_instantiates(self, page, live_server: str) -> None:  # type: ignore[no-untyped-def]
        dp = DashboardPage(page, live_server)
        assert dp.page is page

    def test_dashboard_loads(self, authed_page, seeded_server: str) -> None:  # type: ignore[no-untyped-def]
        dp = DashboardPage(authed_page, seeded_server)
        dp.goto()
        assert "/login" not in authed_page.url
        assert "/setup" not in authed_page.url


class TestSeriesListPage:
    """Verify SeriesListPage POM methods."""

    def test_series_list_instantiates(self, page, live_server: str) -> None:  # type: ignore[no-untyped-def]
        sp = SeriesListPage(page, live_server)
        assert sp.page is page

    def test_series_list_has_search_method(self, page, live_server: str) -> None:  # type: ignore[no-untyped-def]
        sp = SeriesListPage(page, live_server)
        assert callable(sp.search)
        assert callable(sp.get_series_count_text)


class TestHealthPage:
    """Verify HealthPage POM methods."""

    def test_health_page_instantiates(self, page, live_server: str) -> None:  # type: ignore[no-untyped-def]
        hp = HealthPage(page, live_server)
        assert hp.page is page

    def test_health_page_loads(self, authed_page, seeded_server: str) -> None:  # type: ignore[no-untyped-def]
        hp = HealthPage(authed_page, seeded_server)
        hp.goto()
        assert "/health" in authed_page.url
