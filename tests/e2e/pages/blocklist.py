"""Blocklist page object for the standardized blocklist shell."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.e2e.pages.base import BasePage

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page


class BlocklistPage(BasePage):
    """Page object for the blocklist page."""

    def __init__(self, page: Page, base_url: str) -> None:
        super().__init__(page, base_url)

    def goto(self, *, reason: str | None = None, search: str | None = None) -> None:
        params = []
        if reason:
            params.append(f"reason={reason}")
        if search:
            params.append(f"search={search}")
        suffix = ("?" + "&".join(params)) if params else ""
        self.navigate("/blocklist" + suffix)
        self.page_root.wait_for(state="visible", timeout=5000)

    @property
    def page_root(self) -> Locator:
        return self.page.locator("[data-testid='blocklist-page']").first

    @property
    def filters(self) -> Locator:
        return self.page.locator("[data-testid='blocklist-filters']").first

    @property
    def results(self) -> Locator:
        return self.page.locator("[data-testid='blocklist-results']").first

    @property
    def header(self) -> Locator:
        return self.page.locator("[data-testid='blocklist-header']").first

    @property
    def header_metrics(self) -> Locator:
        return self.page.locator("[data-testid='blocklist-header-metrics']").first

    @property
    def footer(self) -> Locator:
        return self.page.locator("[data-testid='page-footer-dock']").first

    @property
    def clear_button(self) -> Locator:
        return self.page.locator("[data-testid='blocklist-clear']").first

    @property
    def reason_filter(self) -> Locator:
        return self.page.locator("[data-testid='blocklist-filter-reason']").first

    def select_reason(self, value: str) -> None:
        self.select_dropdown_option("blocklist-filter-reason", value)

    @property
    def search_input(self) -> Locator:
        return self.page.locator("[data-testid='blocklist-search-input']").first

    @property
    def search_clear(self) -> Locator:
        return self.page.locator("[data-testid='blocklist-search-clear']").first

    def search_value(self) -> str:
        return self.search_input.input_value()

    @property
    def empty_state(self) -> Locator:
        return self.page.locator("[data-testid='blocklist-empty']").first

    @property
    def first_error_toggle(self) -> Locator:
        return self.page.locator("[data-testid^='blocklist-error-toggle-']").first

    @property
    def first_error_detail(self) -> Locator:
        return self.page.locator("[data-testid^='blocklist-error-detail-']").first

    def item(self, text: str) -> Locator:
        return self.results.locator("text=" + text).first
