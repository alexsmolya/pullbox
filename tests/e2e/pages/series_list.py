"""Series list page object for the rewritten /series experience."""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

from tests.e2e.pages.base import BasePage

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page


class SeriesListPage(BasePage):
    """Page object for the /series page."""

    def __init__(self, page: Page, base_url: str) -> None:
        super().__init__(page, base_url)

    def goto(self, query: str = "", *, preferred_view: str | None = None) -> None:
        """Navigate to the series list."""
        if preferred_view is not None:
            parsed = urlparse(self.base_url)
            safe_view = "grid" if preferred_view == "grid" else "list"
            self.page.context.add_cookies(
                [
                    {
                        "name": "series_view",
                        "value": safe_view,
                        "domain": parsed.hostname or "127.0.0.1",
                        "path": "/",
                    }
                ]
            )
        suffix = query if not query or query.startswith("?") else f"?{query}"
        self.navigate(f"/series{suffix}")
        self.wait_until_ready()

    def wait_until_ready(self) -> None:
        """Wait for the mounted /series shell to become interactive."""
        self.toolbar.wait_for(state="visible", timeout=5000)
        self.results_body.wait_for(state="visible", timeout=5000)

    @property
    def toolbar(self) -> Locator:
        return self.page.locator("[data-testid='series-toolbar']").first

    @property
    def summary(self) -> Locator:
        return self.page.locator("[data-testid='series-summary']").first

    @property
    def results_body(self) -> Locator:
        return self.page.locator("[data-testid='series-results-body']").first

    @property
    def pagination(self) -> Locator:
        return self.page.locator("[data-testid='page-dock-pagination']").first

    @property
    def search_input(self) -> Locator:
        return self.page.locator("[data-testid='series-search-input']").first

    @property
    def search_clear(self) -> Locator:
        return self.page.locator("[data-testid='series-search-clear']").first

    def search_value(self) -> str:
        return self.search_input.input_value()

    @property
    def footer(self) -> Locator:
        return self.page.locator("[data-testid='page-footer-dock']").first

    @property
    def select_mode_toolbar(self) -> Locator:
        return self.page.locator("[data-testid='series-select-toolbar']").first

    @property
    def select_mode_toggle(self) -> Locator:
        return self.page.locator("[data-testid='series-select-mode-toggle']").first

    @property
    def select_mode_done(self) -> Locator:
        return self.page.locator("[data-testid='series-select-mode-done']").first

    @property
    def bulk_count(self) -> Locator:
        return self.page.locator("[data-testid='series-bulk-count']").first

    @property
    def select_visible_button(self) -> Locator:
        return self.page.locator("[data-testid='series-select-visible']").first

    @property
    def select_all_results_button(self) -> Locator:
        return self.page.locator("[data-testid='series-select-all-results']").first

    @property
    def deselect_all_button(self) -> Locator:
        return self.page.locator("[data-testid='series-deselect-all']").first

    @property
    def delete_modal(self) -> Locator:
        return self.page.locator("[data-testid='series-delete-modal']").first

    def search(self, query: str) -> None:
        """Trigger the accelerated search from the toolbar."""
        self.search_input.fill(query)
        self.wait_for_query_param("q", query)
        self.wait_for_htmx()

    def clear_search(self) -> None:
        """Clear the active search query and wait for the list to reset."""
        self.search_clear.click()
        self.wait_for_query_param("q", None)
        self.wait_for_htmx()

    def choose_view(self, view: str) -> None:
        """Switch the local-only series view."""
        self.page.locator(f"[data-testid='series-view-{view}']").first.click()
        self.page.wait_for_function(
            """(view) => {
                const cookiePrefix = "series_view=";
                const cookieValue = document.cookie
                    .split("; ")
                    .find((entry) => entry.startsWith(cookiePrefix))
                    ?.slice(cookiePrefix.length);
                return (
                    document.documentElement.getAttribute("data-series-view") === view
                    && window.localStorage.getItem("series_view") === view
                    && decodeURIComponent(cookieValue || "") === view
                );
            }""",
            arg=view,
            timeout=5000,
        )
        expected_selector = (
            "[data-testid='series-collector-wall-view']"
            if view == "grid"
            else "[data-testid='series-mission-control-view']"
        )
        self.page.wait_for_function(
            """(selector) => {
                const target = document.querySelector(selector);
                const empty = document.querySelector("[data-testid='series-empty-state']");
                return Boolean(
                    empty
                    || (
                        target
                        && window.getComputedStyle(target).display !== "none"
                        && target.getBoundingClientRect().height > 0
                    )
                );
            }""",
            arg=expected_selector,
            timeout=5000,
        )
        self.page.evaluate(
            """() => new Promise((resolve) => {
                requestAnimationFrame(() => requestAnimationFrame(resolve));
            })"""
        )

    def current_view(self) -> str | None:
        """Return the current local-only series view."""
        return self.page.evaluate("() => document.documentElement.getAttribute('data-series-view')")

    def set_filter(self, name: str, value: str) -> None:
        """Change a native select-backed filter."""
        self.select_dropdown_option(self._dropdown_testid(name), value)
        self.wait_for_htmx()

    def get_series_count_text(self) -> str | None:
        """Return the mounted summary text."""
        if self.summary.count() == 0:
            return None
        return self.summary.text_content()

    def selected_value(self, name: str) -> str:
        """Return the current value of a native select control."""
        return self.dropdown_value(self._dropdown_testid(name))

    def selected_label(self, name: str) -> str:
        """Return the current label of a native select control."""
        return self.dropdown_label(self._dropdown_testid(name))

    def _dropdown_testid(self, name: str) -> str:
        """Map logical filter names to their rendered dropdown test ids."""
        if name == "per_page":
            return "series-per-page-select"
        return f"series-{name}-select"

    def query_param(self, name: str) -> str | None:
        """Return a URL query parameter from the current page URL."""
        values = parse_qs(urlparse(self.page.url).query).get(name)
        return values[0] if values else None

    def click_next_page(self) -> None:
        """Click the Next pagination control."""
        self.page.locator("[data-testid='series-pagination-next']").first.click()
        self.wait_for_htmx()

    def click_prev_page(self) -> None:
        """Click the Prev pagination control."""
        self.page.locator("[data-testid='series-pagination-prev']").first.click()
        self.wait_for_htmx()

    def click_page(self, page_number: int) -> None:
        """Click a numbered pagination control."""
        self.page.locator(f"[data-testid='series-pagination-page-{page_number}']").first.click()
        self.wait_for_htmx()

    def open_first_series(self) -> None:
        """Open the first visible series detail link."""
        self.visible_series_links().first.click()
        self.page.wait_for_url("**/series/*", timeout=5000)
        self.page.locator("[data-testid='series-detail-page']").first.wait_for(
            state="visible", timeout=5000
        )

    def first_visible_series_title(self) -> str:
        """Return the first visible series title in the active view."""
        return (self.visible_series_links().first.text_content() or "").strip()

    def first_visible_series_href(self) -> str | None:
        """Return the href of the first visible series link in the active view."""
        return self.visible_series_links().first.get_attribute("href")

    def open_first_grid_cover(self) -> None:
        """Open the first visible grid cover link."""
        self.page.locator("[data-testid='series-grid-cover-link']").first.click()
        self.page.wait_for_url("**/series/*", timeout=5000)
        self.page.locator("[data-testid='series-detail-page']").first.wait_for(
            state="visible", timeout=5000
        )

    def visible_series_links(self) -> Locator:
        """Return the visible series links in the active view."""
        return self.page.locator("[data-testid='series-item-link']:visible")

    def get_series_cards(self) -> int:
        """Return the number of visible series items in the active layout."""
        return self.visible_series_links().count()

    def row_for_title(self, title: str) -> Locator:
        """Return the active list or compact item for a series title."""
        return (
            self.page.locator(
                "[data-testid='series-result-row'], [data-testid='series-compact-card'], [data-testid='series-grid-card']"
            )
            .filter(has_text=title)
            .first
        )

    def row_count(self, title: str) -> int:
        """Return how many active items match a series title."""
        return (
            self.page.locator(
                "[data-testid='series-result-row'], [data-testid='series-compact-card'], [data-testid='series-grid-card']"
            )
            .filter(has_text=title)
            .count()
        )

    def toggle_row_selection(self, title: str) -> None:
        """Toggle a row checkbox by series title."""
        self.open_select_mode()
        self.row_for_title(title).locator("[data-testid='series-row-checkbox']").first.click()

    def click_row_delete(self, title: str) -> None:
        """Open the shared delete modal from a row action."""
        self.row_for_title(title).locator("[data-testid='series-row-delete']").first.click()
        self.delete_modal.wait_for(state="visible", timeout=5000)

    def row_is_selected(self, title: str) -> bool:
        """Return whether a row checkbox is checked."""
        return (
            self.row_for_title(title)
            .locator("[data-testid='series-row-checkbox']")
            .first.is_checked()
        )

    def row_has_monitored_indicator(self, title: str) -> bool:
        """Return whether a row is currently showing the monitored/on indicator."""
        indicator = (
            self.row_for_title(title).locator("[data-testid='series-monitored-indicator']").first
        )
        if indicator.count() == 0:
            return False
        classes = indicator.get_attribute("class") or ""
        return " off" not in f" {classes} " and "series-led-off" not in classes

    def selected_count_text(self) -> str:
        """Return the bulk selection count text."""
        return (self.bulk_count.text_content() or "").strip()

    def toolbar_mode(self) -> str | None:
        """Return the active toolbar mode."""
        return self.page.locator("[data-testid='series-page']").first.get_attribute(
            "data-series-toolbar-mode"
        )

    def open_select_mode(self) -> None:
        """Swap the toolbar into select mode if needed."""
        if self.toolbar_mode() == "select":
            return
        self.select_mode_toggle.click()
        try:
            self.page.wait_for_function(
                """() => {
                    const root = document.querySelector("[data-testid='series-page']");
                    const select = document.querySelector("[data-testid='series-select-toolbar']");
                    if (!root || !select) {
                        return false;
                    }
                    const style = window.getComputedStyle(select);
                    const rect = select.getBoundingClientRect();
                    return (
                        root.getAttribute("data-series-toolbar-mode") === "select"
                        && style.display !== "none"
                        && style.visibility !== "hidden"
                        && rect.height > 0
                        && rect.width > 0
                    );
                }""",
                timeout=750,
            )
        except Exception:
            self.page.evaluate(
                """() => {
                    if (window.setSeriesToolbarMode) {
                        window.setSeriesToolbarMode("select");
                    }
                }"""
            )
            try:
                self.page.wait_for_function(
                    """() => {
                        const root = document.querySelector("[data-testid='series-page']");
                        const select = document.querySelector("[data-testid='series-select-toolbar']");
                        if (!root || !select) {
                            return false;
                        }
                        const style = window.getComputedStyle(select);
                        const rect = select.getBoundingClientRect();
                        return (
                            root.getAttribute("data-series-toolbar-mode") === "select"
                            && style.display !== "none"
                            && style.visibility !== "hidden"
                            && rect.height > 0
                            && rect.width > 0
                        );
                    }""",
                    timeout=5000,
                )
            except Exception as exc:
                state = self.page.evaluate(
                    """() => {
                        const root = document.querySelector("[data-testid='series-page']");
                        const select = document.querySelector("[data-testid='series-select-toolbar']");
                        const browse = document.querySelector("[data-testid='series-browse-toolbar']");
                        const toggle = document.querySelector("[data-testid='series-select-mode-toggle']");
                        const selectStyle = select ? window.getComputedStyle(select) : null;
                        const browseStyle = browse ? window.getComputedStyle(browse) : null;
                        const selectRect = select ? select.getBoundingClientRect() : null;
                        return {
                            helperDefined: typeof window.setSeriesToolbarMode === "function",
                            toolbarMode: root ? root.getAttribute("data-series-toolbar-mode") : null,
                            selectDisplay: selectStyle ? selectStyle.display : null,
                            selectVisibility: selectStyle ? selectStyle.visibility : null,
                            selectOpacity: selectStyle ? selectStyle.opacity : null,
                            selectHeight: selectRect ? selectRect.height : null,
                            selectWidth: selectRect ? selectRect.width : null,
                            browseDisplay: browseStyle ? browseStyle.display : null,
                            toggleText: toggle ? toggle.textContent : null,
                        };
                    }"""
                )
                raise AssertionError(f"Unable to enter select mode: {state}") from exc

    def exit_select_mode(self) -> None:
        """Return the toolbar to browse mode if needed."""
        if self.toolbar_mode() != "select":
            return
        self.select_mode_done.click()
        try:
            self.page.wait_for_function(
                """() => {
                    const root = document.querySelector("[data-testid='series-page']");
                    const select = document.querySelector("[data-testid='series-select-toolbar']");
                    if (!root || !select) {
                        return false;
                    }
                    const style = window.getComputedStyle(select);
                    return (
                        root.getAttribute("data-series-toolbar-mode") === "browse"
                        && style.display === "none"
                    );
                }""",
                timeout=750,
            )
        except Exception:
            self.page.evaluate(
                """() => {
                    if (window.setSeriesToolbarMode) {
                        window.setSeriesToolbarMode("browse");
                    }
                }"""
            )
            self.page.wait_for_function(
                """() => {
                    const root = document.querySelector("[data-testid='series-page']");
                    const select = document.querySelector("[data-testid='series-select-toolbar']");
                    if (!root || !select) {
                        return false;
                    }
                    const style = window.getComputedStyle(select);
                    return (
                        root.getAttribute("data-series-toolbar-mode") === "browse"
                        && style.display === "none"
                    );
                }""",
                timeout=5000,
            )

    def visible_row_checkbox_count(self) -> int:
        """Return the number of visible selection checkboxes in the active view."""
        return self.page.locator("[data-testid='series-row-checkbox']:visible").count()

    def select_visible_disabled(self) -> bool:
        """Return whether the select-visible toolbar action is disabled."""
        return self.select_visible_button.is_disabled()

    def apply_bulk_action(self, action: str) -> None:
        """Apply a bulk action and wait for the refresh to complete."""
        self.open_select_mode()
        button = self.page.locator(f"[data-testid='series-bulk-{action}']").first
        with self.page.expect_response(
            lambda response: (
                response.request.method == "PATCH" and response.url.endswith("/api/v1/series/bulk")
            )
        ):
            button.click()

        self.page.wait_for_function("() => !document.querySelector('.htmx-request')")
        self.page.wait_for_function(
            """() => {
                const count = document.querySelector("[data-testid='series-bulk-count']");
                return !!count && count.textContent.includes("0 selected");
            }"""
        )
        self.page.wait_for_function(
            """() => {
                const root = document.querySelector("[data-testid='series-page']");
                return !!root && root.getAttribute("data-series-bulk-busy") === "false";
            }"""
        )

    def clear_bulk_selection(self) -> None:
        """Clear the current bulk selection."""
        self.exit_select_mode()

    def select_visible(self) -> None:
        """Select every visible series in the active results view."""
        self.open_select_mode()
        self.select_visible_button.click()

    def select_all_results(self) -> None:
        """Select every series matching the current filters."""
        self.open_select_mode()
        previous_count = self.selected_count_text()
        self.select_all_results_button.click()
        self.page.wait_for_function(
            """(previousCount) => {
                const count = document.querySelector("[data-testid='series-bulk-count']");
                return !!count && count.textContent.trim() !== previousCount;
            }""",
            arg=previous_count,
            timeout=5000,
        )

    def deselect_all_visible(self) -> None:
        """Clear the current selection while staying in select mode."""
        self.open_select_mode()
        self.deselect_all_button.click()

    def open_bulk_delete_confirm(self) -> None:
        """Open the shared delete modal from the bulk action bar."""
        self.open_select_mode()
        self.page.locator("[data-testid='series-bulk-delete']").first.click()
        self.delete_modal.wait_for(state="visible", timeout=5000)

    def bulk_delete_confirm_visible(self) -> bool:
        """Return whether the shared delete modal is visible."""
        return self.delete_modal.is_visible()

    def confirm_delete(self) -> dict[str, object]:
        """Confirm the shared delete modal and wait for the list refresh."""
        with (
            self.page.expect_response(
                lambda response: (
                    response.request.method == "DELETE"
                    and response.url.endswith("/api/v1/series/bulk")
                )
            ) as delete_response,
            self.page.expect_response(
                lambda response: (
                    response.request.method == "GET"
                    and "/series" in response.url
                    and "_pb_refresh=" in response.url
                )
            ),
        ):
            self.page.locator("[data-testid='series-delete-submit']").first.click()

        self.page.wait_for_function("() => !document.querySelector('.htmx-request')")
        self.page.wait_for_function(
            """() => {
                const count = document.querySelector("[data-testid='series-bulk-count']");
                return !!count && count.textContent.includes("0 selected");
            }"""
        )
        self.page.wait_for_function(
            """() => {
                const root = document.querySelector("[data-testid='series-page']");
                return !!root && root.getAttribute("data-series-bulk-busy") === "false";
            }"""
        )
        self.delete_modal.wait_for(state="hidden", timeout=5000)
        return delete_response.value.request.post_data_json or {}

    def cancel_delete(self) -> None:
        """Cancel the shared delete modal."""
        self.page.locator("[data-testid='series-delete-cancel']").first.click()
        self.delete_modal.wait_for(state="hidden", timeout=5000)

    def toggle_delete_files(self) -> None:
        """Toggle the delete-files checkbox in the shared delete modal."""
        self.page.locator("[data-testid='series-delete-files']").first.click()

    def toggle_delete_folders(self) -> None:
        """Toggle the delete-folders checkbox in the shared delete modal."""
        self.page.locator("[data-testid='series-delete-folders']").first.click()

    def delete_files_checked(self) -> bool:
        """Return whether delete-files is checked."""
        return self.page.locator("[data-testid='series-delete-files']").first.is_checked()

    def delete_files_disabled(self) -> bool:
        """Return whether delete-files is disabled."""
        return self.page.locator("[data-testid='series-delete-files']").first.is_disabled()

    def delete_folder_checked(self) -> bool:
        """Return whether delete-folders is checked."""
        return self.page.locator("[data-testid='series-delete-folders']").first.is_checked()

    def delete_title_text(self) -> str:
        """Return the shared delete modal title text."""
        return (
            self.page.locator("[data-testid='series-delete-title']").first.text_content() or ""
        ).strip()
