"""Utilities page objects for the rewritten utilities UI."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.e2e.pages.base import BasePage

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page


class UtilitiesPage(BasePage):
    """Page object for the /utilities shell."""

    def __init__(self, page: Page, base_url: str) -> None:
        super().__init__(page, base_url)

    def goto(self, tab: str = "utilities") -> None:
        self.navigate(f"/utilities?tab={tab}")
        self.page_root.wait_for(state="visible", timeout=5000)

    @property
    def page_root(self) -> Locator:
        return self.page.locator("[data-testid='utilities-page']").first

    @property
    def body(self) -> Locator:
        return self.page.locator("[data-testid='utilities-body']").first

    @property
    def header(self) -> Locator:
        return self.page.locator("[data-testid='utilities-header']").first

    @property
    def gauges(self) -> Locator:
        return self.page.locator("[data-testid='utilities-gauges']").first

    @property
    def shell(self) -> Locator:
        return self.page.locator("[data-testid='utilities-shell']").first

    @property
    def tabs(self) -> Locator:
        return self.page.locator("[data-testid='utilities-tabs']").first

    @property
    def content(self) -> Locator:
        return self.page.locator("[data-testid='utilities-content']").first

    @property
    def overview_panel(self) -> Locator:
        return self.page.locator("[data-testid='utilities-overview-panel']").first

    @property
    def queue_panel(self) -> Locator:
        return self.page.locator("[data-testid='utilities-queue-panel']").first

    @property
    def history_panel(self) -> Locator:
        return self.page.locator("[data-testid='utilities-history-panel']").first

    @property
    def queue_empty(self) -> Locator:
        return self.page.locator("[data-testid='utilities-queue-empty']").first

    @property
    def history_table(self) -> Locator:
        return self.page.locator("[data-testid='utilities-history-table']").first

    @property
    def history_status_filter(self) -> Locator:
        return self.page.locator("[data-testid='utilities-history-filter-status']").first

    @property
    def history_clear_button(self) -> Locator:
        return self.page.locator("[data-testid='utilities-history-clear']").first

    @property
    def footer_dock(self) -> Locator:
        return self.page.locator("[data-testid='utilities-footer-dock']").first

    def tab(self, key: str) -> Locator:
        return self.page.locator(f"[data-testid='utilities-tab-{key}']").first

    def panel(self, key: str) -> Locator:
        if key == "queue":
            return self.queue_panel
        if key == "history":
            return self.history_panel
        return self.overview_panel

    def switch_tab(self, key: str) -> None:
        self.tab(key).click()
        self.wait_for_query_param("tab", key)
        self.panel(key).wait_for(state="visible", timeout=5000)

    def select_history_status(self, value: str) -> None:
        self.select_dropdown_option("utilities-history-filter-status", value)
        self.wait_for_query_param("utility_history_status", value or None)
        self.wait_for_htmx()
        self.page.wait_for_function(
            "(args) => document.querySelector(args[0])?.value === args[1]",
            arg=[
                "[data-testid='utilities-history-filter-status'] [data-dropdown-select-input]",
                value,
            ],
            timeout=5000,
        )

    @property
    def converter_card(self) -> Locator:
        return self.page.locator("[data-testid='utilities-overview-card-converter']").first

    @property
    def mass_convert_card(self) -> Locator:
        return self.page.locator("[data-testid='utilities-overview-card-mass-convert']").first

    @property
    def mass_rename_card(self) -> Locator:
        return self.page.locator("[data-testid='utilities-overview-card-mass-rename']").first

    @property
    def integrity_card(self) -> Locator:
        return self.page.locator("[data-testid='utilities-overview-card-integrity']").first

    @property
    def db_check_card(self) -> Locator:
        return self.page.locator("[data-testid='utilities-overview-card-db-check']").first

    @property
    def export_card(self) -> Locator:
        return self.page.locator("[data-testid='utilities-overview-card-export']").first

    @property
    def permissions_card(self) -> Locator:
        return self.page.locator("[data-testid='utilities-overview-card-permissions']").first


class UtilityWorkflowPage(BasePage):
    """Shared page object for dedicated utility workflow pages."""

    workflow_key: str
    path: str

    def goto(self) -> None:
        self.navigate(self.path)
        self.page_root.wait_for(state="visible", timeout=5000)

    @property
    def page_root(self) -> Locator:
        return self.page.locator(f"[data-testid='utilities-{self.workflow_key}-page']").first

    @property
    def header(self) -> Locator:
        return self.page.locator(f"[data-testid='utilities-{self.workflow_key}-header']").first

    @property
    def workspace(self) -> Locator:
        return self.page.locator(f"[data-testid='utilities-{self.workflow_key}-workspace']").first

    @property
    def card(self) -> Locator:
        return self.page.locator(f"[data-testid='utilities-{self.workflow_key}-card']").first

    @property
    def back_link(self) -> Locator:
        return self.page.locator(f"[data-testid='utilities-{self.workflow_key}-back-link']").first

    @property
    def footer_dock(self) -> Locator:
        return self.page.locator(f"[data-testid='utilities-{self.workflow_key}-footer-dock']").first


class UtilitiesConverterPage(UtilityWorkflowPage):
    """Page object for the /utilities/converter workflow page."""

    def __init__(self, page: Page, base_url: str) -> None:
        super().__init__(page, base_url)
        self.workflow_key = "converter"
        self.path = "/utilities/converter"

    @property
    def start_button(self) -> Locator:
        return self.page.locator("[data-testid='utilities-converter-start']").first

    @property
    def source_format(self) -> Locator:
        return self.page.locator("[data-testid='utilities-converter-source-format']").first

    @property
    def pdf_quality(self) -> Locator:
        return self.page.locator("[data-testid='utilities-converter-pdf-quality']").first

    def select_source_format(self, value: str) -> None:
        self.select_dropdown_option("utilities-converter-source-format", value)
        self.page.wait_for_function(
            "(args) => document.querySelector(args[0])?.value === args[1]",
            arg=[
                "[data-testid='utilities-converter-source-format'] [data-dropdown-select-input]",
                value,
            ],
            timeout=5000,
        )
        if value == "pdf":
            self.pdf_quality.wait_for(state="visible", timeout=5000)
        else:
            self.pdf_quality.wait_for(state="hidden", timeout=5000)

    def select_pdf_quality(self, value: str) -> None:
        self.select_dropdown_option("utilities-converter-pdf-quality", value)
        self.page.wait_for_function(
            "(args) => document.querySelector(args[0])?.value === args[1]",
            arg=[
                "[data-testid='utilities-converter-pdf-quality'] [data-dropdown-select-input]",
                value,
            ],
            timeout=5000,
        )


class UtilitiesMassConvertPage(UtilityWorkflowPage):
    """Page object for the /utilities/mass-convert workflow page."""

    def __init__(self, page: Page, base_url: str) -> None:
        super().__init__(page, base_url)
        self.workflow_key = "mass-convert"
        self.path = "/utilities/mass-convert"

    @property
    def browse_files_button(self) -> Locator:
        return self.page.locator("[data-testid='utilities-mass-convert-browse-files']").first

    @property
    def browse_folder_button(self) -> Locator:
        return self.page.locator("[data-testid='utilities-mass-convert-browse-folder']").first

    @property
    def start_button(self) -> Locator:
        return self.page.locator("[data-testid='utilities-mass-convert-start']").first

    @property
    def preview_table(self) -> Locator:
        return self.page.locator("[data-testid='utilities-mass-convert-preview-table']").first

    @property
    def trash_folder_input(self) -> Locator:
        return self.page.locator("[data-testid='utilities-mass-convert-trash-folder']").first

    def scope_button(self, value: str) -> Locator:
        return self.page.locator(f"[data-testid='utilities-mass-convert-scope-{value}']").first

    def choose_scope(self, value: str) -> None:
        button = self.scope_button(value)
        button.click()
        self.page.wait_for_function(
            "(selector) => document.querySelector(selector)?.getAttribute('aria-pressed') === 'true'",
            arg=f"[data-testid='utilities-mass-convert-scope-{value}']",
            timeout=5000,
        )


class UtilitiesIntegrityPage(UtilityWorkflowPage):
    """Page object for the /utilities/integrity workflow page."""

    def __init__(self, page: Page, base_url: str) -> None:
        super().__init__(page, base_url)
        self.workflow_key = "integrity"
        self.path = "/utilities/integrity"

    @property
    def browse_button(self) -> Locator:
        return self.page.locator("[data-testid='utilities-integrity-browse']").first

    @property
    def start_button(self) -> Locator:
        return self.page.locator("[data-testid='utilities-integrity-start']").first

    @property
    def quick_mode_card(self) -> Locator:
        return self.page.locator("[data-testid='utilities-integrity-depth-quick']").first

    @property
    def library_scope_button(self) -> Locator:
        return self.page.locator("[data-testid='utilities-integrity-scope-library']").first

    @property
    def remediation_report_button(self) -> Locator:
        return self.page.locator("[data-testid='utilities-integrity-remediation-report']").first

    @property
    def remediation_quarantine_button(self) -> Locator:
        return self.page.locator("[data-testid='utilities-integrity-remediation-quarantine']").first

    @property
    def requeue_search_checkbox(self) -> Locator:
        return self.page.locator("[data-testid='utilities-integrity-requeue-search']").first

    def scope_button(self, value: str) -> Locator:
        return self.page.locator(f"[data-testid='utilities-integrity-scope-{value}']").first

    def remediation_button(self, value: str) -> Locator:
        return self.page.locator(f"[data-testid='utilities-integrity-remediation-{value}']").first

    def choose_depth(self, value: str) -> None:
        self.page.locator(f"[data-testid='utilities-integrity-depth-{value}']").first.click()
        self.page.wait_for_function(
            "(selector) => document.querySelector(selector)?.getAttribute('aria-pressed') === 'true'",
            arg=f"[data-testid='utilities-integrity-depth-{value}']",
            timeout=5000,
        )

    def choose_scope(self, value: str) -> None:
        button = self.scope_button(value)
        button.click()
        self.page.wait_for_function(
            "(selector) => document.querySelector(selector)?.getAttribute('aria-pressed') === 'true'",
            arg=f"[data-testid='utilities-integrity-scope-{value}']",
            timeout=5000,
        )
        if value == "library":
            self.browse_button.wait_for(state="hidden", timeout=5000)
        else:
            self.browse_button.wait_for(state="visible", timeout=5000)

    def choose_remediation(self, value: str) -> None:
        button = self.remediation_button(value)
        button.click()
        self.page.wait_for_function(
            "(selector) => document.querySelector(selector)?.getAttribute('aria-pressed') === 'true'",
            arg=f"[data-testid='utilities-integrity-remediation-{value}']",
            timeout=5000,
        )


class UtilitiesMassRenamePage(UtilityWorkflowPage):
    """Page object for the /utilities/mass-rename workflow page."""

    def __init__(self, page: Page, base_url: str) -> None:
        super().__init__(page, base_url)
        self.workflow_key = "mass-rename"
        self.path = "/utilities/mass-rename"

    @property
    def files_target(self) -> Locator:
        return self.page.locator("[data-testid='utilities-mass-rename-target-files']").first

    @property
    def folders_target(self) -> Locator:
        return self.page.locator("[data-testid='utilities-mass-rename-target-folders']").first

    @property
    def edit_templates_link(self) -> Locator:
        return self.page.locator("[data-testid='utilities-mass-rename-edit-templates']").first

    @property
    def browse_button(self) -> Locator:
        return self.page.locator("[data-testid='utilities-mass-rename-browse']").first

    @property
    def start_button(self) -> Locator:
        return self.page.locator("[data-testid='utilities-mass-rename-start']").first

    @property
    def preview_table(self) -> Locator:
        return self.page.locator("[data-testid='utilities-mass-rename-preview-table']").first

    def scope_button(self, value: str) -> Locator:
        return self.page.locator(f"[data-testid='utilities-mass-rename-scope-{value}']").first

    def choose_target(self, value: str) -> None:
        self.page.locator(f"[data-testid='utilities-mass-rename-target-{value}']").first.click()
        self.page.wait_for_function(
            "(selector) => document.querySelector(selector)?.getAttribute('aria-pressed') === 'true'",
            arg=f"[data-testid='utilities-mass-rename-target-{value}']",
            timeout=5000,
        )

    def choose_scope(self, value: str) -> None:
        button = self.scope_button(value)
        button.click()
        self.page.wait_for_function(
            "(selector) => document.querySelector(selector)?.getAttribute('aria-pressed') === 'true'",
            arg=f"[data-testid='utilities-mass-rename-scope-{value}']",
            timeout=5000,
        )


class UtilitiesDbCheckPage(UtilityWorkflowPage):
    """Page object for the /utilities/db-check workflow page."""

    def __init__(self, page: Page, base_url: str) -> None:
        super().__init__(page, base_url)
        self.workflow_key = "db-check"
        self.path = "/utilities/db-check"

    @property
    def preview_button(self) -> Locator:
        return self.page.locator("[data-testid='utilities-db-check-preview']").first

    @property
    def findings(self) -> Locator:
        return self.page.locator("[data-testid='utilities-db-check-findings']").first

    def run_preview(self) -> None:
        self.preview_button.click()
        self.findings.wait_for(state="visible", timeout=5000)


class UtilitiesExportPage(UtilityWorkflowPage):
    """Page object for the /utilities/export workflow page."""

    def __init__(self, page: Page, base_url: str) -> None:
        super().__init__(page, base_url)
        self.workflow_key = "export"
        self.path = "/utilities/export"

    @property
    def start_button(self) -> Locator:
        return self.page.locator("[data-testid='utilities-export-start']").first

    @property
    def json_options(self) -> Locator:
        return self.page.locator("[data-testid='utilities-export-json-options']").first

    @property
    def pretty_option(self) -> Locator:
        return self.page.locator("[data-testid='utilities-export-json-pretty-option']").first

    @property
    def multi_value_select_all(self) -> Locator:
        return self.page.locator("[data-testid='utilities-export-multi-value-select-all']").first

    @property
    def multi_value_clear_all(self) -> Locator:
        return self.page.locator("[data-testid='utilities-export-multi-value-clear-all']").first

    @property
    def multi_value_grid(self) -> Locator:
        return self.page.locator("[data-testid='utilities-export-multi-value-grid']").first

    def choose_format(self, value: str) -> None:
        self.page.locator(f"[data-testid='utilities-export-format-{value}']").first.click()
        self.page.wait_for_function(
            "(selector) => document.querySelector(selector)?.getAttribute('aria-pressed') === 'true'",
            arg=f"[data-testid='utilities-export-format-{value}']",
            timeout=5000,
        )
        if value == "json":
            self.json_options.wait_for(state="visible", timeout=5000)
        else:
            self.json_options.wait_for(state="hidden", timeout=5000)

    def choose_scope(self, value: str) -> None:
        self.page.locator(f"[data-testid='utilities-export-scope-{value}']").first.click()
        self.page.wait_for_function(
            "(selector) => document.querySelector(selector)?.getAttribute('aria-pressed') === 'true'",
            arg=f"[data-testid='utilities-export-scope-{value}']",
            timeout=5000,
        )

    def selected_field_count(self) -> int:
        return self.page.locator(
            "[data-testid='utilities-export-field-grid'] input[type='checkbox']:checked"
        ).count()


class UtilitiesPermissionsPage(UtilityWorkflowPage):
    """Page object for the /utilities/permissions workflow page."""

    def __init__(self, page: Page, base_url: str) -> None:
        super().__init__(page, base_url)
        self.workflow_key = "permissions"
        self.path = "/utilities/permissions"

    @property
    def start_button(self) -> Locator:
        return self.page.locator("[data-testid='utilities-permissions-start']").first

    @property
    def error_panel(self) -> Locator:
        return self.page.locator("[data-testid='utilities-permissions-error']").first

    @property
    def run_mode_select(self) -> Locator:
        return self.page.locator("[data-testid='utilities-permissions-run-mode']").first

    @property
    def scope_select(self) -> Locator:
        return self.page.locator("[data-testid='utilities-permissions-scope']").first

    @property
    def browse_folder_button(self) -> Locator:
        return self.page.locator("[data-testid='utilities-permissions-browse-folder']").first

    @property
    def browse_files_button(self) -> Locator:
        return self.page.locator("[data-testid='utilities-permissions-browse-files']").first

    @property
    def preview_table(self) -> Locator:
        return self.page.locator("[data-testid='utilities-permissions-preview-table']").first

    @property
    def folder_count(self) -> Locator:
        return self.page.locator("[data-testid='utilities-permissions-folder-count']").first

    @property
    def file_count(self) -> Locator:
        return self.page.locator("[data-testid='utilities-permissions-file-count']").first

    @property
    def folder_mode_input(self) -> Locator:
        return self.page.locator("[data-testid='utilities-permissions-folder-mode']").first

    @property
    def file_mode_input(self) -> Locator:
        return self.page.locator("[data-testid='utilities-permissions-file-mode']").first

    @property
    def confirm_apply_checkbox(self) -> Locator:
        return self.page.locator("[data-testid='utilities-permissions-confirm-apply']").first
