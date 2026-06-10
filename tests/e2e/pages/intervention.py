"""Intervention page object for the standardized shell."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.e2e.pages.base import BasePage

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page


class InterventionPage(BasePage):
    """Page object for the intervention queue page."""

    def __init__(self, page: Page, base_url: str) -> None:
        super().__init__(page, base_url)

    def goto(self) -> None:
        self.navigate("/intervention")
        self.page_root.wait_for(state="visible", timeout=5000)

    @property
    def page_root(self) -> Locator:
        return self.page.locator("[data-testid='intervention-page']").first

    @property
    def shell(self) -> Locator:
        return self.page_root

    @property
    def content(self) -> Locator:
        return self.page_root

    @property
    def tabs(self) -> Locator:
        return self.page.locator("[data-testid='intervention-tabs']").first

    @property
    def header(self) -> Locator:
        return self.page.locator("[data-testid='intervention-header']").first

    @property
    def toolbar(self) -> Locator:
        return self.page.locator("[data-testid='intervention-filters']").first

    @property
    def queue_tab(self) -> Locator:
        return self.page.locator("[data-testid='intervention-tab-queue']").first

    @property
    def history_tab(self) -> Locator:
        return self.page.locator("[data-testid='intervention-tab-history']").first

    @property
    def bulk_toolbar(self) -> Locator:
        return self.page.locator("[data-testid='intervention-selection-count']").first

    @property
    def select_mode_toggle(self) -> Locator:
        return self.page.locator("[data-testid='intervention-select-mode-toggle']").first

    @property
    def select_visible_button(self) -> Locator:
        return self.page.locator("[data-testid='intervention-select-visible']").first

    @property
    def bulk_approve_button(self) -> Locator:
        return self.page.locator("[data-testid='intervention-bulk-approve']").first

    @property
    def bulk_reject_button(self) -> Locator:
        return self.page.locator("[data-testid='intervention-bulk-reject']").first

    @property
    def results(self) -> Locator:
        return self.page.locator("[data-testid='intervention-results']").first

    @property
    def summary_cards(self) -> Locator:
        return self.page.locator("[data-testid='intervention-summary-cards']").first

    @property
    def list_region(self) -> Locator:
        return self.page.locator("[data-testid='intervention-list']").first

    @property
    def first_item_checkbox(self) -> Locator:
        return self.page.locator("#intervention-list [data-intervention-id]").first

    @property
    def empty_state(self) -> Locator:
        return self.page.locator("[data-testid='intervention-empty']").first

    @property
    def search_input(self) -> Locator:
        return self.page.locator("[data-testid='intervention-search-input']").first

    @property
    def history_panel(self) -> Locator:
        return self.page.locator("[data-testid='intervention-history-panel']").first

    def item(self, pending_id: int) -> Locator:
        return self.page.locator(f"[data-testid='intervention-item-{pending_id}']").first

    def item_checkbox(self, pending_id: int) -> Locator:
        return self.page.locator(f"[data-testid='intervention-item-checkbox-{pending_id}']").first

    def item_by_text(self, text: str) -> Locator:
        return self.list_region.locator("text=" + text).first
