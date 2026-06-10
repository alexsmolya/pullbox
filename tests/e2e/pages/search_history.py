"""Search history page object for the standardized shell."""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlencode

from tests.e2e.pages.base import BasePage

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page


class SearchHistoryPage(BasePage):
    """Page object for the search history page."""

    def __init__(self, page: Page, base_url: str) -> None:
        super().__init__(page, base_url)

    def goto(
        self,
        *,
        search_type: str | None = None,
        confidence: str | None = None,
        search: str | None = None,
    ) -> None:
        params: dict[str, str] = {}
        if search_type:
            params["search_type"] = search_type
        if confidence:
            params["confidence"] = confidence
        if search:
            params["search"] = search
        suffix = ("?" + urlencode(params)) if params else ""
        self.navigate("/search-history" + suffix)
        self.page_root.wait_for(state="visible", timeout=5000)

    @property
    def page_root(self) -> Locator:
        return self.page.locator("[data-testid='search-history-page']").first

    @property
    def filters(self) -> Locator:
        return self.page.locator("[data-testid='search-history-filters']").first

    @property
    def results(self) -> Locator:
        return self.page.locator("[data-testid='search-history-results']").first

    @property
    def header(self) -> Locator:
        return self.page.locator("[data-testid='search-history-header']").first

    @property
    def header_metrics(self) -> Locator:
        return self.page.locator("[data-testid='search-history-header-metrics']").first

    @property
    def footer(self) -> Locator:
        return self.page.locator("[data-testid='page-footer-dock']").first

    @property
    def table(self) -> Locator:
        return self.page.locator("[data-testid='search-history-table']").first

    @property
    def type_filter(self) -> Locator:
        return self.dropdown("search-history-filter-type")

    @property
    def confidence_filter(self) -> Locator:
        return self.dropdown("search-history-filter-confidence")

    @property
    def search_input(self) -> Locator:
        return self.page.locator("[data-testid='search-history-search-input']").first

    @property
    def search_clear(self) -> Locator:
        return self.page.locator("[data-testid='search-history-search-clear']").first

    @property
    def clear_button(self) -> Locator:
        return self.page.locator("[data-testid='search-history-clear']").first

    @property
    def empty_state(self) -> Locator:
        return self.page.locator("[data-testid='search-history-empty']").first

    def row(self, text: str) -> Locator:
        return self.results.locator("tr", has_text=text).first

    def sort_header(self, label: str) -> Locator:
        return self.results.locator("thead button", has_text=label).first

    @property
    def first_detail_toggle(self) -> Locator:
        return self.page.locator("[data-testid^='search-history-detail-toggle-']").first

    @property
    def first_detail_row(self) -> Locator:
        return self.page.locator(
            "[data-testid^='search-history-detail-']:not([data-testid^='search-history-detail-toggle-'])"
        ).first

    @property
    def first_remove_button(self) -> Locator:
        return self.page.locator("[data-testid^='search-history-remove-']").first

    def select_type_filter(self, value: str) -> None:
        self.select_dropdown_option("search-history-filter-type", value)
        self.wait_for_htmx()

    def select_confidence_filter(self, value: str) -> None:
        self.select_dropdown_option("search-history-filter-confidence", value)
        self.wait_for_htmx()
