"""Post-processing page object for the refreshed shell."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.e2e.pages.base import BasePage

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page


class PostProcessingPage(BasePage):
    """Page object for the post-processing page."""

    def __init__(self, page: Page, base_url: str) -> None:
        super().__init__(page, base_url)

    def goto(
        self,
        *,
        tab: str = "queue",
        result: str = "all",
        client: str = "",
        search: str = "",
        sort: str | None = None,
    ) -> None:
        params = [f"tab={tab}", f"result={result}"]
        if client:
            params.append(f"client={client}")
        if search:
            params.append(f"search={search}")
        if sort:
            params.append(f"sort={sort}")
        self.navigate("/post-processing?" + "&".join(params))
        self.page_root.wait_for(state="visible", timeout=5000)

    @property
    def page_root(self) -> Locator:
        return self.page.locator("[data-testid='post-processing-page']").first

    @property
    def shell(self) -> Locator:
        return self.page.locator("[data-testid='post-processing-shell']").first

    @property
    def content(self) -> Locator:
        return self.page.locator("[data-testid='post-processing-content']").first

    @property
    def header(self) -> Locator:
        return self.page.locator("[data-testid='post-processing-header']").first

    @property
    def gauges(self) -> Locator:
        return self.page.locator("[data-testid='pp-gauges']").first

    @property
    def tabs(self) -> Locator:
        return self.page.locator("[data-testid='post-processing-tabs']").first

    @property
    def queue_panel(self) -> Locator:
        return self.page.locator("[data-testid='pp-queue-panel']").first

    @property
    def queue_empty(self) -> Locator:
        return self.page.locator("[data-testid='pp-queue-empty']").first

    @property
    def queue_active_section(self) -> Locator:
        return self.page.locator("[data-testid='pp-queue-active-section']").first

    @property
    def queue_imported_section(self) -> Locator:
        return self.page.locator("[data-testid='pp-queue-imported-section']").first

    @property
    def queue_imported_empty(self) -> Locator:
        return self.page.locator("[data-testid='pp-queue-imported-empty']").first

    @property
    def history_panel(self) -> Locator:
        return self.page.locator("[data-testid='pp-history-panel']").first

    @property
    def history_toolbar(self) -> Locator:
        return self.page.locator("[data-testid='pp-history-toolbar']").first

    @property
    def history_empty(self) -> Locator:
        return self.page.locator("[data-testid='pp-history-empty']").first

    @property
    def history_results(self) -> Locator:
        return self.page.locator("[data-testid='pp-history-results']").first

    @property
    def history_search_input(self) -> Locator:
        return self.page.locator("[data-testid='pp-history-search']").first

    @property
    def history_clear_button(self) -> Locator:
        return self.page.locator("[data-testid='pp-history-clear']").first

    @property
    def footer_dock(self) -> Locator:
        return self.page.locator("[data-testid='pp-footer-dock']").first

    @property
    def queue_items(self) -> Locator:
        return self.page.locator("[data-testid='pp-queue-item']")

    @property
    def queue_details_toggle(self) -> Locator:
        return self.page.locator("[data-testid='pp-queue-item-details-toggle']").first

    def tab(self, key: str) -> Locator:
        return self.page.locator(f"[data-testid='post-processing-tab-{key}']").first

    def switch_tab(self, key: str) -> None:
        self.tab(key).click()
        self.wait_for_htmx()

    def apply_result_filter(self, value: str) -> None:
        self.select_dropdown_option("pp-history-filter-result", value)
        self.wait_for_hx_get_query_param(
            "[data-testid='pp-history-results']",
            "result",
            value or None,
        )
        self.wait_for_htmx()

    def apply_client_filter(self, value: str) -> None:
        self.select_dropdown_option("pp-history-filter-client", value)
        self.wait_for_hx_get_query_param(
            "[data-testid='pp-history-results']",
            "client",
            value or None,
        )
        self.wait_for_htmx()

    def search_history(self, query: str) -> None:
        self.history_search_input.fill(query)
        self.history_search_input.press("Enter")
        self.wait_for_htmx()

    def sort_history(self, field: str) -> None:
        self.page.locator(f"[data-testid='pp-history-sort-{field}']").first.click()
        self.wait_for_htmx()

    def history_remove_button(self) -> Locator:
        return self.page.locator("[data-testid^='pp-history-remove-']").first

    def history_item(self, text: str) -> Locator:
        return self.history_panel.locator("text=" + text).first

    def queue_item(self, text: str) -> Locator:
        return self.queue_panel.locator("text=" + text).first
