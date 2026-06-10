"""Downloads page object for the rewritten downloads UI."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.e2e.pages.base import BasePage

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page


class DownloadsPage(BasePage):
    """Page object for the downloads page."""

    def __init__(self, page: Page, base_url: str) -> None:
        super().__init__(page, base_url)

    def goto(self, tab: str = "queue") -> None:
        self.navigate(f"/downloads?tab={tab}")
        self.page_root.wait_for(state="visible", timeout=5000)

    @property
    def page_root(self) -> Locator:
        return self.page.locator("[data-testid='downloads-page']").first

    @property
    def tabs(self) -> Locator:
        return self.page.locator("[data-testid='downloads-tabs']").first

    @property
    def content(self) -> Locator:
        return self.page.locator("[data-testid='downloads-content']").first

    @property
    def header(self) -> Locator:
        return self.page.locator("[data-testid='downloads-header']").first

    @property
    def gauges(self) -> Locator:
        return self.page.locator("[data-testid='downloads-gauges']").first

    @property
    def queue_panel(self) -> Locator:
        return self.page.locator("[data-testid='downloads-queue-panel']").first

    @property
    def queue_active_section(self) -> Locator:
        return self.page.locator("[data-testid='downloads-queue-active-section']").first

    @property
    def queue_waiting_section(self) -> Locator:
        return self.page.locator("[data-testid='downloads-queue-waiting-section']").first

    @property
    def queue_active_empty(self) -> Locator:
        return self.page.locator("[data-testid='downloads-queue-active-empty']").first

    @property
    def queue_waiting_empty(self) -> Locator:
        return self.page.locator("[data-testid='downloads-queue-waiting-empty']").first

    @property
    def footer_dock(self) -> Locator:
        return self.page.locator("[data-testid='downloads-footer-dock']").first

    @property
    def queue_empty(self) -> Locator:
        return self.queue_active_empty

    @property
    def history_panel(self) -> Locator:
        return self.page.locator("[data-testid='downloads-history-panel']").first

    @property
    def history_results(self) -> Locator:
        return self.page.locator("[data-testid='downloads-history-results']").first

    @property
    def history_table(self) -> Locator:
        return self.page.locator("[data-testid='downloads-history-table']").first

    @property
    def history_toolbar(self) -> Locator:
        return self.page.locator("[data-testid='downloads-history-toolbar']").first

    @property
    def history_clear_button(self) -> Locator:
        return self.page.locator("[data-testid='downloads-history-clear']").first

    @property
    def history_search_input(self) -> Locator:
        return self.page.locator("[data-testid='downloads-history-search']").first

    @property
    def history_search_clear(self) -> Locator:
        return self.page.locator("[data-testid='downloads-history-search-clear']").first

    def tab(self, key: str) -> Locator:
        return self.page.locator(f"[data-testid='downloads-tab-{key}']").first

    def switch_tab(self, key: str) -> None:
        self.tab(key).click()
        self.wait_for_query_param("tab", key)
        panel = self.history_panel if key == "history" else self.queue_panel
        panel.wait_for(state="visible", timeout=5000)

    def queue_item(self, text: str) -> Locator:
        return (
            self.queue_panel.locator("[data-testid='downloads-queue-item']")
            .filter(has_text=text)
            .first
        )

    def history_item(self, text: str) -> Locator:
        return self.history_panel.locator("text=" + text).first

    @property
    def first_history_error_toggle(self) -> Locator:
        return self.history_panel.locator("[aria-label='Toggle error details']").first

    @property
    def first_history_error_detail(self) -> Locator:
        return self.history_panel.locator("[data-testid^='downloads-history-error-detail-']").first

    @property
    def history_status_filter(self) -> Locator:
        return self.page.locator("[data-testid='downloads-history-filter-status']").first

    @property
    def history_client_filter(self) -> Locator:
        return self.page.locator("[data-testid='downloads-history-filter-client']").first

    def select_history_status(self, value: str) -> None:
        self.select_dropdown_option("downloads-history-filter-status", value)
        self.wait_for_hx_get_query_param(
            "[data-testid='downloads-history-results']",
            "status",
            value or None,
        )
        self.wait_for_htmx()

    def search_history(self, query: str) -> None:
        self.history_search_input.fill(query)
        self.history_search_input.press("Enter")
        self.wait_for_htmx()

    @property
    def history_empty(self) -> Locator:
        return self.page.locator("[data-testid='downloads-history-empty']").first
