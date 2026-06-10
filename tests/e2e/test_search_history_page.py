"""Focused browser coverage for the standardized search history page."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from tests.e2e.pages.search_history import SearchHistoryPage

pytestmark = pytest.mark.e2e


def _query_param(url: str, name: str) -> str | None:
    values = parse_qs(urlparse(url).query).get(name)
    return values[0] if values else None


class TestSearchHistoryPage:
    """Behavior-first E2E checks for the search history shell."""

    def test_search_history_renders_stable_shell(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        search_history = SearchHistoryPage(authed_page, seeded_server)
        search_history.goto()

        assert search_history.page_root.is_visible()
        assert search_history.header.is_visible()
        assert search_history.header_metrics.is_visible()
        assert search_history.filters.is_visible()
        assert search_history.results.is_visible()
        assert search_history.footer.is_visible()
        assert search_history.table.is_visible()
        assert search_history.clear_button.is_visible()
        assert search_history.row("Batman #2").is_visible()

    def test_search_history_filter_keeps_shell_stable(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        search_history = SearchHistoryPage(authed_page, seeded_server)
        search_history.goto()

        search_history.select_type_filter("manual")

        assert authed_page.locator("[data-testid='search-history-page']").count() == 1
        assert authed_page.locator("[data-testid='search-history-filters']").count() == 1
        assert authed_page.locator("[data-testid='search-history-results']").count() == 1
        assert search_history.page_root.is_visible()
        assert search_history.results.is_visible()
        assert search_history.row("Batman #2").is_visible()
        assert search_history.dropdown_label("search-history-filter-type") == "Manual"

    def test_search_history_results_wrapper_allows_filter_panels_to_escape_table_bounds(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        search_history = SearchHistoryPage(authed_page, seeded_server)
        search_history.goto()

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

    def test_search_history_confidence_filter_keeps_shell_stable(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        search_history = SearchHistoryPage(authed_page, seeded_server)
        search_history.goto()

        search_history.select_confidence_filter("high")

        assert authed_page.locator("[data-testid='search-history-page']").count() == 1
        assert authed_page.locator("[data-testid='search-history-filters']").count() == 1
        assert authed_page.locator("[data-testid='search-history-results']").count() == 1
        assert search_history.page_root.is_visible()
        assert search_history.results.is_visible()
        assert search_history.row("Batman #2").is_visible()
        assert search_history.dropdown_label("search-history-filter-confidence") == "High"

    def test_search_history_search_keeps_shell_stable(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        search_history = SearchHistoryPage(authed_page, seeded_server)
        search_history.goto()

        search_history.search_input.fill("2")
        # Wait for HTMX to update the URL and re-render results.
        # Use expect_navigation pattern instead of wait_for_htmx to avoid
        # "execution context destroyed" race on Chromium.
        authed_page.wait_for_url("**/search-history?*search=2*", timeout=5000)
        authed_page.wait_for_load_state("networkidle")

        assert _query_param(authed_page.url, "search") == "2"
        assert search_history.page_root.is_visible()
        assert search_history.results.is_visible()
        assert search_history.row("Batman #2").is_visible()

    def test_search_history_sort_keeps_shell_stable(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        search_history = SearchHistoryPage(authed_page, seeded_server)
        search_history.goto()

        search_history.sort_header("Grabbed").click()
        search_history.wait_for_htmx()

        assert authed_page.locator("[data-testid='search-history-page']").count() == 1
        assert authed_page.locator("[data-testid='search-history-filters']").count() == 1
        assert authed_page.locator("[data-testid='search-history-results']").count() == 1
        assert search_history.page_root.is_visible()
        assert search_history.results.is_visible()
        assert search_history.row("Batman #2").is_visible()

    def test_search_history_detail_toggle_expands_inline_row(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        search_history = SearchHistoryPage(authed_page, seeded_server)
        search_history.goto()

        toggle = search_history.first_detail_toggle
        detail = search_history.first_detail_row
        diagnostics_toggle = authed_page.locator(
            "[data-testid^='search-history-diagnostics-toggle-']"
        ).first
        diagnostics_panel = authed_page.locator(
            "[data-testid^='search-history-diagnostics-panel-']"
        ).first

        assert toggle.is_visible()
        assert detail.is_hidden()

        toggle.click()

        detail.wait_for(state="visible")
        detail.locator("[data-testid^='search-history-detail-content-']").first.wait_for(
            state="visible",
            timeout=5000,
        )
        detail_text = detail.text_content() or ""
        assert "Best Match" in detail_text
        assert "Search Outcome" in detail_text
        assert "Download Log" in detail_text
        if diagnostics_toggle.count() and diagnostics_toggle.is_visible():
            assert diagnostics_panel.is_hidden()
            diagnostics_toggle.click()
            diagnostics_panel.wait_for(state="visible")

    def test_search_history_row_delete_removes_entry(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        search_history = SearchHistoryPage(authed_page, seeded_server)
        search_history.goto()

        authed_page.route(
            "**/api/v1/search/history/*",
            lambda route: route.fulfill(status=204),
        )
        authed_page.route(
            "**/search-history*",
            lambda route: route.fulfill(
                status=200,
                content_type="text/html",
                body="""
<div id="search-history-header-metrics" data-testid="search-history-header-metrics" class="downloads-header-summary" hx-swap-oob="outerHTML">
  <div class="downloads-header-copy">
    <h1 class="downloads-title">SEARCH <span>HISTORY</span></h1>
    <p class="downloads-subtitle">2 searches · 1 grabbed · 0 queued · 0 rejected</p>
  </div>
  <div data-testid="search-history-gauges" class="downloads-gauges"></div>
</div>
<input id="search-history-sort-input" type="hidden" name="sort" value="-created_at" hx-swap-oob="outerHTML">
<div id="search-history-clear-slot" hx-swap-oob="outerHTML">
  <button type="button" data-testid="search-history-clear" class="btn-danger control-size-sm shrink-0 whitespace-nowrap">Clear History</button>
</div>
<div id="page-footer-dock" data-testid="page-footer-dock" hx-swap-oob="innerHTML">
  <div class="page-dock-inner page-dock-inner-status-only" data-testid="page-dock-inner">
    <div class="page-dock-status" data-testid="page-dock-status">
      <span class="page-dock-status-item"><span class="page-dock-status-label">total</span><strong class="page-dock-status-value">2 searches</strong></span>
      <span class="page-dock-status-item"><span class="page-dock-status-label">grabbed</span><strong class="page-dock-status-value">1</strong></span>
      <span class="page-dock-status-item"><span class="page-dock-status-label">queued</span><strong class="page-dock-status-value">0</strong></span>
      <span class="page-dock-status-item"><span class="page-dock-status-label">rejected</span><strong class="page-dock-status-value">0</strong></span>
    </div>
  </div>
</div>
<div id="search-history-results-body" data-testid="search-history-results-body">
  <table data-testid="search-history-table" class="downloads-table">
    <tbody>
      <tr id="search-history-row-1"><td>Batman #1</td></tr>
    </tbody>
  </table>
</div>
""",
            ),
        )

        search_history.first_remove_button.click()
        confirm_dialog = authed_page.locator("#pb-confirm-dialog")
        confirm_dialog.locator("button", has_text="Remove").click()

        assert "Batman #1" in (search_history.results.text_content() or "")

    def test_search_history_clear_button_removes_all_entries(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        search_history = SearchHistoryPage(authed_page, seeded_server)
        search_history.goto()

        authed_page.route(
            "**/api/v1/search/history",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body='{"deleted":3}',
            ),
        )
        authed_page.route(
            "**/search-history",
            lambda route: route.fulfill(
                status=200,
                content_type="text/html",
                body="""
<div id="search-history-header-metrics" data-testid="search-history-header-metrics" class="downloads-header-summary" hx-swap-oob="outerHTML">
  <div class="downloads-header-copy">
    <h1 class="downloads-title">SEARCH <span>HISTORY</span></h1>
    <p class="downloads-subtitle">0 searches · 0 grabbed · 0 queued · 0 rejected</p>
  </div>
  <div data-testid="search-history-gauges" class="downloads-gauges"></div>
</div>
<input id="search-history-sort-input" type="hidden" name="sort" value="-created_at" hx-swap-oob="outerHTML">
<div id="search-history-clear-slot" hx-swap-oob="outerHTML"></div>
<div id="page-footer-dock" data-testid="page-footer-dock" hx-swap-oob="innerHTML">
  <div class="page-dock-inner page-dock-inner-status-only" data-testid="page-dock-inner">
    <div class="page-dock-status" data-testid="page-dock-status">
      <span class="page-dock-status-item"><span class="page-dock-status-label">total</span><strong class="page-dock-status-value">0 searches</strong></span>
      <span class="page-dock-status-item"><span class="page-dock-status-label">grabbed</span><strong class="page-dock-status-value">0</strong></span>
      <span class="page-dock-status-item"><span class="page-dock-status-label">queued</span><strong class="page-dock-status-value">0</strong></span>
      <span class="page-dock-status-item"><span class="page-dock-status-label">rejected</span><strong class="page-dock-status-value">0</strong></span>
    </div>
  </div>
</div>
<div id="search-history-results-body" data-testid="search-history-results-body">
  <div data-testid="search-history-empty" class="downloads-empty-state is-history">
    <p class="downloads-empty-title">No search history</p>
    <p class="downloads-empty-copy">Search operations will be logged here as they run.</p>
  </div>
</div>
""",
            ),
        )

        search_history.clear_button.click()
        confirm_dialog = authed_page.locator("#pb-confirm-dialog")
        confirm_dialog.locator("button", has_text="Clear History").click()

        search_history.empty_state.wait_for(state="visible")
        assert "No search history" in (search_history.empty_state.text_content() or "")
