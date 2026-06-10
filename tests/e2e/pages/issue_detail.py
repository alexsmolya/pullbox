"""Issue detail page object for the rewrite."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.e2e.pages.base import BasePage

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page


class IssueDetailPage(BasePage):
    """Page object for the /issues/{id} detail page."""

    def __init__(self, page: Page, base_url: str) -> None:
        super().__init__(page, base_url)

    def goto(self, issue_id: int) -> None:
        """Navigate to an issue detail page."""
        self.navigate(f"/issues/{issue_id}")
        self.wait_until_ready()

    def wait_until_ready(self) -> None:
        """Wait for the stable issue-detail shell to render."""
        self.hero.wait_for(state="visible", timeout=5000)
        self.hero_actions_panel.wait_for(state="visible", timeout=5000)

    @property
    def page_shell(self) -> Locator:
        return self.page.locator("[data-testid='issue-detail-page']").first

    @property
    def hero(self) -> Locator:
        return self.page.locator("[data-testid='issue-detail-hero']").first

    @property
    def hero_summary_panel(self) -> Locator:
        return self.page.locator("[data-testid='issue-detail-hero-summary-panel']").first

    @property
    def hero_actions_panel(self) -> Locator:
        return self.page.locator("[data-testid='issue-detail-hero-actions-panel']").first

    @property
    def footer(self) -> Locator:
        return self.page.locator("[data-testid='page-footer-dock']").first

    @property
    def status_row(self) -> Locator:
        return self.page.locator("[data-testid='issue-detail-status-row']").first

    @property
    def back_link(self) -> Locator:
        return self.page.locator("[data-testid='issue-detail-back-link']").first

    @property
    def search_region(self) -> Locator:
        return self.page.locator("[data-testid='issue-search-modal']").first

    @property
    def search_empty_state(self) -> Locator:
        return self.page.locator("[data-testid='issue-search-results-empty-state']").first

    @property
    def search_results(self) -> Locator:
        return self.page.locator("[data-testid='issue-search-results']").first

    @property
    def search_results_empty_state(self) -> Locator:
        return self.page.locator("[data-testid='issue-search-results-empty-state']").first

    @property
    def file_browser_modal(self) -> Locator:
        return self.page.locator("[data-testid='file-browser-modal']").first

    @property
    def import_modal(self) -> Locator:
        return self.page.locator("[data-testid='issue-import-modal']").first

    @property
    def description_section(self) -> Locator:
        return self.page.locator("[data-testid='issue-description-section']").first

    @property
    def description_title(self) -> Locator:
        return self.page.locator("[data-testid='issue-description-title']").first

    @property
    def creators_section(self) -> Locator:
        return self.page.locator("[data-testid='issue-creators-section']").first

    @property
    def creators_title(self) -> Locator:
        return self.page.locator("[data-testid='issue-creators-title']").first

    @property
    def library_file_section(self) -> Locator:
        return self.page.locator("[data-testid='issue-library-file-section']").first

    @property
    def library_file_title(self) -> Locator:
        return self.page.locator("[data-testid='issue-library-file-title']").first

    @property
    def library_file_copy(self) -> Locator:
        return self.page.locator("[data-testid='issue-library-file-copy']").first

    def open_back_link(self) -> None:
        """Click the back link and wait for the swap to settle."""
        self.back_link.click()
        self.page.wait_for_url("**/series/**", timeout=5000)
        self.page.locator("[data-testid='series-detail-page']").first.wait_for(
            state="visible", timeout=5000
        )

    def open_import_file_browser(self) -> None:
        """Open the shared file browser from the issue action rail."""
        self.page.locator("[data-testid='issue-action-import']").first.click()
        self.file_browser_modal.wait_for(state="visible", timeout=5000)

    def close_file_browser(self) -> None:
        """Close the file browser modal."""
        self.page.locator("[data-testid='file-browser-close']").first.click()
        self.file_browser_modal.wait_for(state="hidden", timeout=5000)

    def run_manual_search(self) -> None:
        """Open the manual search modal and wait for results to load."""
        self.page.locator("[data-testid='issue-action-manual-search']").first.click()
        self.search_region.wait_for(state="visible", timeout=5000)
        self.page.wait_for_function(
            """() => {
                const modal = document.querySelector("[data-testid='issue-search-modal']");
                if (!modal) return false;

                const isVisible = (node) => Boolean(
                    node
                    && window.getComputedStyle(node).display !== "none"
                    && window.getComputedStyle(node).visibility !== "hidden"
                    && node.getClientRects().length > 0
                );

                const loading = modal.querySelector(".issue-search-loading-state");
                const results = modal.querySelector("[data-testid='issue-search-results']");
                const emptyState = modal.querySelector("[data-testid='issue-search-results-empty-state']");

                return !isVisible(loading) && (isVisible(results) || isVisible(emptyState));
            }""",
            timeout=10000,
        )

    def close_manual_search(self) -> None:
        """Close the manual search modal."""
        self.page.locator("[data-testid='issue-search-close']").first.click()
        self.search_region.wait_for(state="hidden", timeout=5000)

    def toggle_status(self) -> None:
        """Toggle the issue status and wait for the detail page to reload."""
        self.page.locator("[data-testid='issue-action-toggle']").first.click()
        self.page.wait_for_load_state("networkidle", timeout=5000)
        self.wait_until_ready()
