"""Focused E2E coverage for the Pull List page."""

from __future__ import annotations

import pytest

from tests.e2e.pages.base import BasePage

pytestmark = pytest.mark.e2e


class TestPullListPage:
    """Behavior-first E2E coverage for /pull-list."""

    def test_per_page_selection_updates_results_and_url(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        pull_list = BasePage(authed_page, seeded_server)
        pull_list.navigate("/pull-list")
        pull_list.dropdown("pull-list-per-page-select").wait_for(state="visible", timeout=5000)

        pull_list.select_dropdown_option("pull-list-per-page-select", "50")
        pull_list.wait_for_query_param("per_page", "50")
        pull_list.wait_for_htmx()

        assert pull_list.dropdown_value("pull-list-per-page-select") == "50"
        assert authed_page.locator("[data-testid='pull-list-results-body']").first.is_visible()
