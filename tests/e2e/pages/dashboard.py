"""Dashboard page object for the mission-control dashboard."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.e2e.pages.base import BasePage

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page


class DashboardPage(BasePage):
    """Page object for the redesigned dashboard."""

    def __init__(self, page: Page, base_url: str) -> None:
        super().__init__(page, base_url)

    def goto(self) -> None:
        """Navigate to the dashboard."""
        self.navigate("/")
        self.page_root.wait_for(state="visible", timeout=5000)

    @property
    def page_root(self) -> Locator:
        return self.page.locator("[data-testid='dashboard-page']").first

    @property
    def mission_control(self) -> Locator:
        return self.page.locator("[data-testid='dashboard-mission-control']").first

    @property
    def mission_summary(self) -> Locator:
        return self.page.locator("[data-testid='dashboard-mission-summary']").first

    @property
    def mission_title_block(self) -> Locator:
        return self.page.locator("[data-testid='dashboard-mission-title-block']").first

    @property
    def mission_gauges(self) -> Locator:
        return self.page.locator("[data-testid='dashboard-mission-gauges']").first

    def gauge(self, key: str) -> Locator:
        return self.page.locator(f"[data-testid='dashboard-gauge-{key}']").first

    @property
    def scoreboard(self) -> Locator:
        return self.page.locator("[data-testid='dashboard-scoreboard']").first

    @property
    def alerts(self) -> Locator:
        return self.page.locator("[data-testid='dashboard-alerts']").first

    @property
    def first_alert_sys_led(self) -> Locator:
        return self.page.locator("[data-testid='dashboard-alert-sys-led']").first

    @property
    def download_exceptions_panel(self) -> Locator:
        return self.page.locator("[data-testid='dashboard-download-exceptions']").first

    @property
    def download_exception_all_clear(self) -> Locator:
        return self.page.locator("[data-testid='dashboard-download-exception-all-clear']").first

    @property
    def first_download_exception_sys_led(self) -> Locator:
        return self.page.locator("[data-testid='dashboard-download-exception-sys-led']").first

    @property
    def recent_activity(self) -> Locator:
        return self.page.locator("[data-testid='dashboard-recent-activity']").first

    @property
    def footer_dock(self) -> Locator:
        return self.page.locator("[data-testid='dashboard-footer-dock']").first
