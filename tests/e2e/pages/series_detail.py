"""Series detail page object for the rewrite."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.e2e.pages.base import BasePage

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page


class SeriesDetailPage(BasePage):
    """Page object for the /series/{id} detail page."""

    def __init__(self, page: Page, base_url: str) -> None:
        super().__init__(page, base_url)

    def goto(self, series_id: int) -> None:
        self.navigate(f"/series/{series_id}")
        self.wait_until_ready()

    def wait_until_ready(self) -> None:
        self.hero.wait_for(state="visible", timeout=5000)
        self.issues_section.wait_for(state="visible", timeout=5000)

    @property
    def page_shell(self) -> Locator:
        return self.page.locator("[data-testid='series-detail-page']").first

    @property
    def hero(self) -> Locator:
        return self.page.locator("[data-testid='series-detail-hero']").first

    @property
    def hero_summary_panel(self) -> Locator:
        return self.page.locator("[data-testid='series-detail-hero-summary-panel']").first

    @property
    def hero_actions_panel(self) -> Locator:
        return self.page.locator("[data-testid='series-detail-hero-actions-panel']").first

    @property
    def monitor_control(self) -> Locator:
        return self.page.locator("[data-testid='series-action-monitor-control']").first

    @property
    def monitor_label(self) -> Locator:
        return self.page.locator("[data-testid='series-action-monitor-label']").first

    @property
    def monitor_toggle(self) -> Locator:
        return self.page.locator("[data-testid='series-action-monitor-toggle'] input").first

    @property
    def refresh_button(self) -> Locator:
        return self.page.locator("[data-testid='series-action-refresh']").first

    @property
    def back_link(self) -> Locator:
        return self.page.locator("[data-testid='series-detail-back-link']").first

    @property
    def related_series_section(self) -> Locator:
        return self.page.locator("[data-testid='series-detail-related-series-section']").first

    @property
    def issues_section(self) -> Locator:
        return self.page.locator("[data-testid='series-detail-issues-section']").first

    @property
    def delete_modal(self) -> Locator:
        return self.page.locator("[data-testid='series-detail-delete-modal']").first

    @property
    def search_modal(self) -> Locator:
        return self.page.locator("[data-testid='issue-search-modal']").first

    @property
    def footer(self) -> Locator:
        return self.page.locator("[data-testid='page-footer-dock']").first

    @property
    def issues_status_filter(self) -> Locator:
        return self.dropdown("series-detail-issues-status-select")

    @property
    def issue_links(self) -> Locator:
        return self.page.locator("[data-testid='series-issue-link']")

    def open_back_link(self) -> None:
        self.back_link.click()
        self.page.wait_for_url("**/series**", timeout=5000)
        self.page.locator("[data-testid='series-page']").first.wait_for(
            state="visible", timeout=5000
        )

    def open_delete_modal(self) -> None:
        self.page.locator("[data-testid='series-action-delete']").first.click()
        self.delete_modal.wait_for(state="visible", timeout=5000)

    def close_delete_modal(self) -> None:
        self.page.locator("[data-testid='series-delete-cancel']").first.click()
        self.delete_modal.wait_for(state="hidden", timeout=5000)

    def toggle_delete_files(self) -> None:
        self.page.locator("[data-testid='series-delete-files']").first.click()

    def toggle_delete_folders(self) -> None:
        self.page.locator("[data-testid='series-delete-folders']").first.click()

    def delete_files_checked(self) -> bool:
        return self.page.locator("[data-testid='series-delete-files']").first.is_checked()

    def delete_files_disabled(self) -> bool:
        return self.page.locator("[data-testid='series-delete-files']").first.is_disabled()

    def delete_folder_checked(self) -> bool:
        return self.page.locator("[data-testid='series-delete-folders']").first.is_checked()

    def open_manual_search_modal(self) -> None:
        self.page.locator("[data-testid='series-issue-manual-search']").first.click()
        self.search_modal.wait_for(state="visible", timeout=5000)

    def close_manual_search_modal(self) -> None:
        self.page.locator("[data-testid='issue-search-close']").first.click()
        self.search_modal.wait_for(state="hidden", timeout=5000)

    def select_issue_status_filter(self, value: str) -> None:
        self.select_dropdown_option("series-detail-issues-status-select", value)
        self.wait_for_htmx()

    def first_issue_href(self) -> str | None:
        return self.issue_links.first.get_attribute("href")

    def open_first_issue(self) -> None:
        self.issue_links.first.click()
        self.page.wait_for_url("**/issues/**", timeout=5000)
        self.page.locator("[data-testid='issue-detail-page']").first.wait_for(
            state="visible", timeout=5000
        )
