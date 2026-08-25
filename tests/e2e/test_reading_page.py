"""Focused browser coverage for the private Reading workspace."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from playwright.sync_api import Page

pytestmark = pytest.mark.e2e


def _goto_reading(page: Page, base_url: str, *, view: str = "continue") -> None:
    page.goto(f"{base_url}/reading?view={view}")
    page.locator("[data-testid='reading-page']").wait_for(state="visible")


class TestReadingPage:
    def test_workspace_is_keyboard_reachable_and_responsive(
        self,
        authed_page: Page,
        seeded_server: str,
    ) -> None:
        _goto_reading(authed_page, seeded_server)

        heading = authed_page.locator("[data-testid='reading-title']")
        assert heading.is_visible()
        assert heading.get_attribute("role") is None
        assert heading.evaluate("element => element.tagName") == "H1"
        assert authed_page.locator("[data-testid='reading-card']").count() == 1
        assert authed_page.get_by_text("Page 2 of 3 · 66%", exact=True).is_visible()
        assert (
            authed_page.locator("[data-testid='sidebar-link-reading']").get_attribute(
                "aria-current"
            )
            == "page"
        )

        want_tab = authed_page.locator("[data-testid='reading-view-want-to-read']")
        want_tab.focus()
        assert want_tab.evaluate("element => element === document.activeElement") is True

        authed_page.set_viewport_size({"width": 320, "height": 720})
        assert authed_page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert authed_page.locator("[data-testid='reading-card']").bounding_box() is not None

    def test_queue_mutation_refreshes_the_reading_fragment(
        self,
        authed_page: Page,
        seeded_server: str,
    ) -> None:
        _goto_reading(authed_page, seeded_server)

        add_button = authed_page.get_by_role("button", name="Add to Want to Read")
        add_button.click()
        authed_page.get_by_role("button", name="Remove from Want to Read").wait_for(state="visible")

        _goto_reading(authed_page, seeded_server, view="want-to-read")
        remove_button = authed_page.get_by_role("button", name="Remove from Want to Read")
        assert remove_button.is_visible()
        remove_button.click()

        authed_page.get_by_text("Your reading queue is clear.", exact=True).wait_for(
            state="visible"
        )
        assert authed_page.locator("[data-testid='reading-card']").count() == 0

    def test_failed_mutation_keeps_the_card_and_reports_recovery_copy(
        self,
        authed_page: Page,
        seeded_server: str,
    ) -> None:
        _goto_reading(authed_page, seeded_server)
        authed_page.route(
            "**/api/v1/reader/issues/*/completion",
            lambda route: route.fulfill(status=500, content_type="application/json", body="{}"),
        )

        authed_page.get_by_role("button", name="Mark read").click()

        error = authed_page.get_by_text("That reading update didn’t save. Try again.", exact=True)
        error.wait_for(state="visible")
        assert error.get_attribute("role") == "alert"
        assert authed_page.locator("[data-testid='reading-card']").count() == 1
