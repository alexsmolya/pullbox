"""Focused browser coverage for the standardized blocklist page."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from tests.e2e.pages.blocklist import BlocklistPage

pytestmark = pytest.mark.e2e


def _query_param(url: str, name: str) -> str | None:
    values = parse_qs(urlparse(url).query).get(name)
    return values[0] if values else None


class TestBlocklistPage:
    """Behavior-first E2E checks for the blocklist shell."""

    def test_blocklist_renders_stable_shell(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        blocklist = BlocklistPage(authed_page, seeded_server)
        blocklist.goto()

        assert blocklist.page_root.is_visible()
        assert blocklist.header.is_visible()
        assert blocklist.header_metrics.is_visible()
        assert blocklist.filters.is_visible()
        assert blocklist.results.is_visible()
        assert blocklist.footer.is_visible()
        assert blocklist.clear_button.is_visible()
        assert blocklist.item("Batman 999 (2016) [Digital] Team-DCP").is_visible()

    def test_blocklist_filter_and_search_keep_shell_stable(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        blocklist = BlocklistPage(authed_page, seeded_server)
        blocklist.goto()

        blocklist.select_reason("manual")
        blocklist.wait_for_htmx()

        assert blocklist.page_root.is_visible()
        assert authed_page.locator("[data-testid='blocklist-filters']").count() == 1
        assert authed_page.locator("[data-testid='blocklist-results']").count() == 1
        assert blocklist.item("Saga 073 (2024) [Manual] Minutemen").is_visible()

        blocklist.search_input.fill("Batman 999")
        authed_page.wait_for_timeout(400)
        blocklist.wait_for_htmx()

        assert blocklist.page_root.is_visible()
        assert authed_page.locator("[data-testid='blocklist-filters']").count() == 1
        assert authed_page.locator("[data-testid='blocklist-results']").count() == 1
        assert blocklist.empty_state.is_visible()

    def test_blocklist_results_wrapper_allows_filter_panels_to_escape_table_bounds(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        blocklist = BlocklistPage(authed_page, seeded_server)
        blocklist.goto()

        wrap_style = authed_page.locator(".downloads-table-wrap").first.evaluate(
            """
            node => {
              const style = window.getComputedStyle(node);
              return {
                overflowX: style.overflowX,
                overflowY: style.overflowY,
                position: style.position,
              };
            }
            """
        )

        assert wrap_style == {
            "overflowX": "visible",
            "overflowY": "visible",
            "position": "relative",
        }

    def test_blocklist_search_autosubmits_after_typing(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        blocklist = BlocklistPage(authed_page, seeded_server)
        blocklist.goto()

        blocklist.search_input.click()
        authed_page.keyboard.type("TotallyMissingBlockedRelease", delay=35)
        authed_page.wait_for_timeout(350)
        blocklist.wait_for_htmx()

        assert _query_param(authed_page.url, "search") == "TotallyMissingBlockedRelease"
        assert blocklist.search_value() == "TotallyMissingBlockedRelease"
        assert blocklist.empty_state.is_visible()

    def test_blocklist_search_history_reuses_recent_query(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        authed_page.add_init_script(
            """() => {
                localStorage.removeItem('pullbox.searchHistory.blocklist');
            }"""
        )
        blocklist = BlocklistPage(authed_page, seeded_server)
        blocklist.goto()

        blocklist.search_input.click()
        authed_page.keyboard.type("TotallyMissingBlockedRelease", delay=35)
        authed_page.wait_for_timeout(350)
        blocklist.wait_for_htmx()
        assert _query_param(authed_page.url, "search") == "TotallyMissingBlockedRelease"

        blocklist.search_clear.click()
        blocklist.wait_for_htmx()
        assert _query_param(authed_page.url, "search") in (None, "")

        blocklist.search_input.click()
        history_panel = authed_page.locator("[data-testid='blocklist-search-history-panel']").first
        history_panel.wait_for(state="visible")
        history_panel.locator(
            "[data-search-history-item]", has_text="TotallyMissingBlockedRelease"
        ).first.click()
        blocklist.wait_for_htmx()

        assert _query_param(authed_page.url, "search") == "TotallyMissingBlockedRelease"
        assert blocklist.search_value() == "TotallyMissingBlockedRelease"
        assert blocklist.empty_state.is_visible()

    def test_blocklist_backspace_to_empty_keeps_history_open(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        authed_page.add_init_script(
            """() => {
                localStorage.removeItem('pullbox.searchHistory.blocklist');
            }"""
        )
        blocklist = BlocklistPage(authed_page, seeded_server)
        blocklist.goto()

        blocklist.search_input.click()
        authed_page.keyboard.type("TotallyMissingBlockedRelease", delay=35)
        authed_page.wait_for_timeout(350)
        blocklist.wait_for_htmx()
        assert _query_param(authed_page.url, "search") == "TotallyMissingBlockedRelease"

        blocklist.search_input.click()
        authed_page.keyboard.press("ControlOrMeta+A")
        authed_page.keyboard.press("Backspace")
        blocklist.wait_for_htmx()

        history_panel = authed_page.locator("[data-testid='blocklist-search-history-panel']").first
        history_panel.wait_for(state="visible")

        assert blocklist.search_value() == ""
        assert _query_param(authed_page.url, "search") in (None, "")
        assert history_panel.locator(
            "[data-search-history-item]",
            has_text="TotallyMissingBlockedRelease",
        ).first.is_visible()

    def test_blocklist_sort_keeps_shell_stable(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        blocklist = BlocklistPage(authed_page, seeded_server)
        blocklist.goto()

        authed_page.locator("[data-testid='blocklist-sort-title']").click()
        blocklist.wait_for_htmx()

        assert blocklist.page_root.is_visible()
        assert authed_page.locator("[data-testid='blocklist-filters']").count() == 1
        assert authed_page.locator("[data-testid='blocklist-results']").count() == 1
        assert blocklist.item("Batman Annual 001 (2016) [Rejected] Empire").is_visible()

    def test_blocklist_error_details_toggle_expands_inline_row(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        blocklist = BlocklistPage(authed_page, seeded_server)
        blocklist.goto()

        toggle = blocklist.first_error_toggle
        detail = blocklist.first_error_detail

        assert toggle.is_visible()
        assert detail.is_hidden()

        toggle.click()

        detail.wait_for(state="visible")
        assert "Post-processing failed after repeated retries." in (detail.text_content() or "")
        assert "Error details" not in (detail.text_content() or "")

    def test_blocklist_clear_button_removes_all_entries(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        blocklist = BlocklistPage(authed_page, seeded_server)
        blocklist.goto()

        authed_page.route(
            "**/api/v1/blocklist/clear",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body='{"removed":3}',
            ),
        )
        authed_page.route(
            "**/blocklist",
            lambda route: route.fulfill(
                status=200,
                content_type="text/html",
                body="""
<div id="blocklist-header-metrics" data-testid="blocklist-header-metrics" class="downloads-header-summary" hx-swap-oob="outerHTML">
  <div class="downloads-header-copy">
    <h1 class="downloads-title">BLOCK<span>LIST</span></h1>
    <p class="downloads-subtitle">0 blocked · 0 failed · 0 rejected · 0 manual</p>
  </div>
  <div data-testid="blocklist-gauges" class="downloads-gauges"></div>
</div>
<input id="blocklist-sort-input" type="hidden" name="sort" value="-created_at" hx-swap-oob="outerHTML">
<div id="blocklist-clear-slot" hx-swap-oob="outerHTML"></div>
<div id="page-footer-dock" data-testid="page-footer-dock" hx-swap-oob="innerHTML">
  <div class="page-dock-inner page-dock-inner-status-only" data-testid="page-dock-inner">
    <div class="page-dock-status" data-testid="page-dock-status">
      <span class="page-dock-status-item"><span class="page-dock-status-label">total</span><strong class="page-dock-status-value">0 blocked</strong></span>
      <span class="page-dock-status-item"><span class="page-dock-status-label">failed</span><strong class="page-dock-status-value">0</strong></span>
      <span class="page-dock-status-item"><span class="page-dock-status-label">rejected</span><strong class="page-dock-status-value">0</strong></span>
      <span class="page-dock-status-item"><span class="page-dock-status-label">manual</span><strong class="page-dock-status-value">0</strong></span>
    </div>
  </div>
</div>
<div id="blocklist-results-body" data-testid="blocklist-results-body">
  <div data-testid="blocklist-empty" class="downloads-empty-state is-history">
    <p class="downloads-empty-title">Blocklist is clear</p>
    <p class="downloads-empty-copy">Failed, rejected, and manually blocked releases will appear here.</p>
  </div>
</div>
""",
            ),
        )

        assert blocklist.clear_button.is_visible()
        blocklist.clear_button.click()

        confirm_dialog = authed_page.locator("#pb-confirm-dialog")
        confirm_dialog.locator("button", has_text="Clear Blocklist").click()

        blocklist.empty_state.wait_for(state="visible")
        assert not blocklist.clear_button.is_visible()
        assert "Blocklist is clear" in (blocklist.empty_state.text_content() or "")

    def test_blocklist_clear_search_resets_to_unfiltered_results(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        blocklist = BlocklistPage(authed_page, seeded_server)
        blocklist.goto()

        blocklist.search_input.fill("TotallyMissingBlockedRelease")
        blocklist.search_clear.wait_for(state="visible")
        assert blocklist.search_clear.evaluate("el => getComputedStyle(el).position") == "absolute"
        field_box = authed_page.locator(
            "[data-testid='blocklist-search-field']"
        ).first.bounding_box()
        clear_box = blocklist.search_clear.bounding_box()
        assert field_box is not None
        assert clear_box is not None
        assert field_box["y"] <= clear_box["y"] <= field_box["y"] + field_box["height"]
        authed_page.wait_for_timeout(350)
        blocklist.wait_for_htmx()

        assert blocklist.empty_state.is_visible()

        blocklist.search_clear.click()
        blocklist.wait_for_htmx()

        assert blocklist.search_value() == ""
        assert "search=TotallyMissingBlockedRelease" not in authed_page.url
        restored_item = blocklist.item("Batman 999 (2016) [Digital] Team-DCP")
        restored_item.wait_for(state="visible")
        assert restored_item.is_visible()
