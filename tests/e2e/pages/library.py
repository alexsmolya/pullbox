"""Library page object for the standardized library shell."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from tests.e2e.pages.base import BasePage

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page


class LibraryPage(BasePage):
    """Page object for the library page."""

    def __init__(self, page: Page, base_url: str) -> None:
        super().__init__(page, base_url)

    def goto(self) -> None:
        self.navigate("/library")
        self.page_root.wait_for(state="visible", timeout=5000)

    def goto_path(self, path: str) -> None:
        self.navigate(f"/library?path={path}")
        self.page_root.wait_for(state="visible", timeout=5000)

    @property
    def page_root(self) -> Locator:
        return self.page.locator("[data-testid='library-page']").first

    @property
    def directory_panel(self) -> Locator:
        return self.page.locator("[data-testid='library-directory-panel']").first

    @property
    def tree_header(self) -> Locator:
        return self.page.locator("[data-testid='library-tree-header']").first

    @property
    def tree_list(self) -> Locator:
        return self.page.locator("[data-testid='library-tree-list']").first

    @property
    def browser_toolbar(self) -> Locator:
        return self.page.locator("[data-testid='library-browser-toolbar']").first

    @property
    def stats_grid(self) -> Locator:
        return self.page.locator("[data-testid='library-stats-grid']").first

    @property
    def footer_strip(self) -> Locator:
        return self.page.locator("[data-testid='library-footer-strip']").first

    @property
    def matching_banner(self) -> Locator:
        return self.page.locator("[data-testid='library-matching-banner']").first

    @property
    def breadcrumbs(self) -> Locator:
        return self.page.locator("[data-testid='library-browser-breadcrumbs']").first

    @property
    def current_breadcrumb(self) -> Locator:
        return self.page.locator("[data-testid='library-browser-current-crumb']").first

    @property
    def browser_table(self) -> Locator:
        return self.page.locator("[data-testid='library-browser-table']").first

    @property
    def browser_table_wrap(self) -> Locator:
        return self.page.locator(".library-browser__table-wrap").first

    @property
    def context_menu(self) -> Locator:
        return self.page.locator("[data-testid='library-context-menu']").first

    @property
    def properties_modal(self) -> Locator:
        return self.page.locator("[data-testid='library-properties-modal']").first

    @property
    def rename_modal(self) -> Locator:
        return self.page.locator("[data-testid='library-rename-modal']").first

    @property
    def rename_stale_modal(self) -> Locator:
        return self.page.locator("[data-testid='library-rename-stale-modal']").first

    @property
    def rename_form(self) -> Locator:
        return self.page.locator("[data-testid='library-rename-form']").first

    @property
    def rename_input(self) -> Locator:
        return self.page.locator("[data-testid='library-rename-input']").first

    @property
    def rename_path_preview(self) -> Locator:
        return self.page.locator("[data-testid='library-rename-preview-path']").first

    @property
    def rename_action_note(self) -> Locator:
        return self.page.locator("[data-testid='library-rename-action-note']").first

    @property
    def auto_rename_modal(self) -> Locator:
        return self.page.locator("[data-testid='library-auto-rename-modal']").first

    @property
    def auto_rename_action_note(self) -> Locator:
        return self.page.locator("[data-testid='library-auto-rename-action-note']").first

    @property
    def convert_modal(self) -> Locator:
        return self.page.locator("[data-testid='library-convert-modal']").first

    @property
    def convert_action_note(self) -> Locator:
        return self.page.locator("[data-testid='library-convert-action-note']").first

    @property
    def delete_file_modal(self) -> Locator:
        return self.page.locator("[data-testid='library-delete-file-modal']").first

    @property
    def delete_folder_modal(self) -> Locator:
        return self.page.locator("[data-testid='library-delete-folder-modal']").first

    @property
    def delete_series_modal(self) -> Locator:
        return self.page.locator("[data-testid='library-delete-series-modal']").first

    def stat_card(self, key: str) -> Locator:
        return self.page.locator(f"[data-testid='library-stat-{key}']").first

    def row_link(self, name: str) -> Locator:
        return self.browser_table.locator(f"a:has-text('{name}')").first

    def row_text(self, name: str) -> Locator:
        return self.browser_table.locator(f"tbody tr:has-text('{name}')").first

    def tree_label(self, name: str) -> Locator:
        return self.page.locator(".library-browser__tree-node", has_text=name).first

    def context_action(self, key: str) -> Locator:
        return self.page.locator(f"[data-testid='library-context-action-{key}']").first

    def open_folder(self, name: str) -> None:
        self.row_link(name).click()
        self.page.wait_for_url(re.compile(r".*/library\?path=.*"), timeout=5000)
        self.page_root.wait_for(state="visible", timeout=5000)

    def right_click_row(self, name: str) -> None:
        self.row_text(name).click(button="right")
        self.context_menu.wait_for(state="visible", timeout=5000)

    def right_click_tree_label(self, name: str) -> None:
        self.tree_label(name).click(button="right")
        self.context_menu.wait_for(state="visible", timeout=5000)

    def create_test_file(self, path: str, content: bytes = b"test") -> None:
        Path(path).write_bytes(content)
