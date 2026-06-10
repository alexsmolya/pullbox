"""Health dashboard page object — encapsulates the /health page."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.e2e.pages.base import BasePage

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page


class HealthPage(BasePage):
    """Page object for the /health dashboard."""

    def __init__(self, page: Page, base_url: str) -> None:
        super().__init__(page, base_url)

    def goto(self) -> None:
        """Navigate to the health dashboard."""
        self.navigate("/health")
        self.page_root.wait_for(state="visible", timeout=5000)

    @property
    def page_root(self) -> Locator:
        return self.page.locator("[data-testid='health-page']").first

    @property
    def component_page_root(self) -> Locator:
        return self.page.locator("[data-testid='health-component-page']").first

    @property
    def mission_control(self) -> Locator:
        return self.page.locator("[data-testid='health-mission-control']").first

    @property
    def scoreboard(self) -> Locator:
        return self.page.locator("[data-testid='health-scoreboard']").first

    @property
    def component_registry(self) -> Locator:
        return self.page.locator("[data-testid='health-component-registry']").first

    @property
    def footer_dock(self) -> Locator:
        return self.page.locator("[data-testid='health-footer-dock']").first

    @property
    def status_region(self) -> Locator:
        return self.page.locator("[data-testid='health-status-region']").first

    @property
    def detail_status_region(self) -> Locator:
        return self.page.locator("[data-testid='health-component-status-region']").first

    @property
    def refresh_button(self) -> Locator:
        return self.page.locator("[data-testid='health-refresh-button']").first

    @property
    def detail_refresh_button(self) -> Locator:
        return self.page.locator("[data-testid='health-detail-refresh-button']").first

    @property
    def first_component_card(self) -> Locator:
        return self.page.locator("[data-health-component-card]").first

    def component_card(self, key: str) -> Locator:
        """Return a specific health component card by its component key."""
        return self.page.locator(f"[data-health-component='{key}']").first

    def detail_panel(self, key: str) -> Locator:
        """Return the dedicated health detail panel for a component key."""
        return self.page.locator(f"[data-testid='health-component-detail-{key}']").first

    @property
    def detail_back_link(self) -> Locator:
        return self.page.locator("[data-testid='health-detail-back-link']").first

    def get_component_count(self) -> int:
        """Return the number of health check component cards."""
        return self.page.locator("[data-health-component-card]").count()
