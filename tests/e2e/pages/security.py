"""Security page object for the rewritten security shell."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.e2e.pages.base import BasePage

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page


class SecurityPage(BasePage):
    """Page object for the /security shell."""

    def __init__(self, page: Page, base_url: str) -> None:
        super().__init__(page, base_url)

    def goto(self, tab: str = "authentication") -> None:
        self.navigate(f"/security?tab={tab}")
        self.page_root.wait_for(state="visible", timeout=5000)

    @property
    def page_root(self) -> Locator:
        return self.page.locator("[data-testid='security-page']").first

    @property
    def header(self) -> Locator:
        return self.page.locator("[data-testid='security-header']").first

    @property
    def page_title(self) -> Locator:
        return self.page.locator("[data-testid='security-page-title']").first

    @property
    def body(self) -> Locator:
        return self.page.locator("[data-testid='security-body']").first

    @property
    def tabs(self) -> Locator:
        return self.page.locator("[data-testid='security-tabs']").first

    @property
    def content(self) -> Locator:
        return self.page.locator("[data-testid='security-content']").first

    @property
    def footer_dock(self) -> Locator:
        return self.page.locator("[data-testid='security-footer-dock']").first

    def tab(self, key: str) -> Locator:
        return self.page.locator(f"[data-testid='security-tab-{key}']").first

    def panel(self, key: str) -> Locator:
        return self.page.locator(f"[data-testid='security-panel-{key}']").first

    def switch_tab(self, key: str) -> None:
        self.tab(key).click()
        self.wait_for_query_param("tab", key)
        self.panel(key).wait_for(state="visible", timeout=5000)

    @property
    def audit_type_dropdown(self) -> Locator:
        return self.dropdown("security-audit-type-select")

    def select_audit_type(self, value: str) -> None:
        self.select_dropdown_option("security-audit-type-select", value)
        self.page.wait_for_function(
            """([root, expected]) => {
                const label = document.querySelector(`[data-testid="${root}"] [data-dropdown-select-trigger-label]`);
                return !!(label && label.textContent && label.textContent.toLowerCase().includes(expected.toLowerCase().replace(/_/g, " ")));
            }""",
            arg=["security-audit-type-select", value],
        )
