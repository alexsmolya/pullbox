"""System page object for the rewritten system shell."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.e2e.pages.base import BasePage

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page


class SystemPage(BasePage):
    """Page object for the /system shell."""

    def __init__(self, page: Page, base_url: str) -> None:
        super().__init__(page, base_url)

    def goto(self, tab: str = "about") -> None:
        self.navigate(f"/system?tab={tab}")
        self.page_root.wait_for(state="visible", timeout=5000)

    @property
    def page_root(self) -> Locator:
        return self.page.locator("[data-testid='system-page']").first

    @property
    def header(self) -> Locator:
        return self.page.locator("[data-testid='system-header']").first

    @property
    def body(self) -> Locator:
        return self.page.locator("[data-testid='system-body']").first

    @property
    def tabs(self) -> Locator:
        return self.page.locator("[data-testid='system-tabs']").first

    @property
    def content(self) -> Locator:
        return self.page.locator("[data-testid='system-content']").first

    def tab(self, key: str) -> Locator:
        return self.page.locator(f"[data-testid='system-tab-{key}']").first

    def panel(self, key: str) -> Locator:
        return self.page.locator(f"[data-testid='system-panel-{key}']").first

    def switch_tab(self, key: str) -> None:
        self.tab(key).click()
        self.wait_for_query_param("tab", key)
        self.panel(key).wait_for(state="visible", timeout=5000)

    @property
    def support_debug_duration_select(self) -> Locator:
        return self.page.locator("[data-testid='system-support-debug-duration-select']").first
