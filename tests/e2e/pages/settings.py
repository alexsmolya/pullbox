"""Settings page object for the rewritten settings shell."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.e2e.pages.base import BasePage

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page


class SettingsPage(BasePage):
    """Page object for the /settings shell."""

    def __init__(self, page: Page, base_url: str) -> None:
        super().__init__(page, base_url)

    def goto(self, tab: str = "general") -> None:
        self.navigate(f"/settings?tab={tab}")
        self.page_root.wait_for(state="visible", timeout=5000)

    @property
    def page_root(self) -> Locator:
        return self.page.locator("[data-testid='settings-page']").first

    @property
    def header(self) -> Locator:
        return self.page.locator("[data-testid='settings-header']").first

    @property
    def page_title(self) -> Locator:
        return self.page.locator("[data-testid='settings-page-title']").first

    @property
    def body(self) -> Locator:
        return self.page.locator("[data-testid='settings-body']").first

    @property
    def tabs(self) -> Locator:
        return self.page.locator("[data-testid='settings-tabs']").first

    @property
    def content(self) -> Locator:
        return self.page.locator("[data-testid='settings-content']").first

    @property
    def footer_dock(self) -> Locator:
        return self.page.locator("[data-testid='settings-footer-dock']").first

    def tab(self, key: str) -> Locator:
        return self.page.locator(f"[data-testid='settings-tab-{key}']").first

    def panel(self, key: str) -> Locator:
        return self.page.locator(f"[data-testid='settings-panel-{key}']").first

    def switch_tab(self, key: str) -> None:
        self.tab(key).click()
        self.wait_for_query_param("tab", key)
        self.panel(key).wait_for(state="visible", timeout=5000)
