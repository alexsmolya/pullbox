"""Base page object with common navigation and utility methods."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page


class BasePage:
    """Base page object with common navigation and utility methods.

    All POMs inherit from this class to share navigation, HTMX wait,
    and toast assertion capabilities.
    """

    def __init__(self, page: Page, base_url: str) -> None:
        self.page = page
        self.base_url = base_url

    def navigate(self, path: str) -> None:
        """Navigate to a path relative to the base URL."""
        url = f"{self.base_url}{path}"
        self.page.goto(url)

    def wait_for_htmx(self, *, timeout: int = 5000) -> None:
        """Wait for HTMX to finish all pending requests and settle."""
        from tests.e2e.conftest import wait_for_htmx

        wait_for_htmx(self.page, timeout=timeout)

    def wait_for_query_param(self, name: str, value: str | None, *, timeout: int = 5000) -> None:
        """Wait for a specific URL query parameter to reach the expected value."""
        self.page.wait_for_function(
            """([key, expected]) => {
                const actual = new URL(window.location.href).searchParams.get(key);
                if (expected === null) {
                    return actual === null || actual === "";
                }
                return actual === expected;
            }""",
            arg=[name, value],
            timeout=timeout,
        )

    def wait_for_hx_get_query_param(
        self,
        selector: str,
        name: str,
        value: str | None,
        *,
        timeout: int = 5000,
    ) -> None:
        """Wait for an element's hx-get URL to expose the expected query parameter."""
        self.page.wait_for_function(
            """([targetSelector, key, expected]) => {
                const node = document.querySelector(targetSelector);
                if (!node) return false;
                const hxGet = node.getAttribute('hx-get');
                if (!hxGet) return false;
                const actual = new URL(hxGet, window.location.origin).searchParams.get(key);
                if (expected === null) {
                    return actual === null || actual === '';
                }
                return actual === expected;
            }""",
            arg=[selector, name, value],
            timeout=timeout,
        )

    def get_toast_message(self) -> str | None:
        """Return the text of the first visible toast, or None."""
        toast = self.page.locator("[data-toast]").first
        if toast.is_visible():
            return toast.text_content()
        return None

    def is_sidebar_visible(self) -> bool:
        """Check if the sidebar navigation is visible."""
        sidebar = self.page.locator("aside")
        return sidebar.count() > 0 and sidebar.first.is_visible()

    def get_page_title(self) -> str:
        """Return the current page's <title> text."""
        return self.page.title()

    def round_trip_tab_visibility(self, *, timeout: int = 5000) -> None:
        """Simulate a visibility hidden->visible round-trip on the current tab."""
        self.page.evaluate(
            """() => {
                const originalVisibility = Object.getOwnPropertyDescriptor(document, "visibilityState");
                const originalHidden = Object.getOwnPropertyDescriptor(document, "hidden");
                let state = "visible";

                Object.defineProperty(document, "visibilityState", {
                    configurable: true,
                    get() {
                        return state;
                    },
                });
                Object.defineProperty(document, "hidden", {
                    configurable: true,
                    get() {
                        return state === "hidden";
                    },
                });

                try {
                    state = "hidden";
                    document.dispatchEvent(new Event("visibilitychange"));
                    state = "visible";
                    document.dispatchEvent(new Event("visibilitychange"));
                } finally {
                    if (originalVisibility) {
                        Object.defineProperty(document, "visibilityState", originalVisibility);
                    } else {
                        delete document.visibilityState;
                    }

                    if (originalHidden) {
                        Object.defineProperty(document, "hidden", originalHidden);
                    } else {
                        delete document.hidden;
                    }
                }
            }""",
        )
        self.page.wait_for_function(
            "() => document.visibilityState === 'visible'",
            timeout=timeout,
        )

    def dropdown(self, testid: str) -> Locator:
        """Return a shared custom dropdown root by test id."""
        return self.page.locator(f"[data-testid='{testid}']").first

    def select_dropdown_option(self, testid: str, value: str) -> None:
        """Choose a value from a shared custom dropdown."""
        root = self.dropdown(testid)
        root.locator("[data-dropdown-select-trigger]").first.click()
        panel = self.page.locator("[data-dropdown-select-panel]:visible").first
        panel.wait_for(state="visible", timeout=5000)
        escaped_value = value.replace("\\", "\\\\").replace('"', '\\"')
        panel.locator(f'[data-dropdown-option][data-value="{escaped_value}"]').first.click()
        panel.wait_for(state="hidden", timeout=5000)

    def dropdown_value(self, testid: str) -> str:
        """Return the submitted value of a shared custom dropdown."""
        return self.dropdown(testid).locator("[data-dropdown-select-input]").first.input_value()

    def dropdown_label(self, testid: str) -> str:
        """Return the visible label of a shared custom dropdown."""
        return (
            self.dropdown(testid)
            .locator("[data-dropdown-select-trigger-label]")
            .first.text_content()
            or ""
        ).strip()
