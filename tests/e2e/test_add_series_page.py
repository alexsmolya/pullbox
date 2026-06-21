"""Focused browser coverage for the rewritten add-series page."""

from __future__ import annotations

from contextlib import suppress
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import expect

from tests.e2e.conftest import wait_for_htmx

pytestmark = pytest.mark.e2e


class TestAddSeriesPage:
    """Behavior-first checks for /series/add."""

    def test_add_series_renders_stable_shell_and_series_header_contract(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        authed_page.set_viewport_size({"width": 1600, "height": 1200})
        authed_page.goto(f"{seeded_server}/series/add")
        authed_page.wait_for_load_state("networkidle")

        assert authed_page.locator("[data-testid='add-series-page']").is_visible()
        assert authed_page.locator("[data-testid='add-series-header']").is_visible()
        assert authed_page.locator("[data-testid='add-series-gauges']").is_visible()
        assert authed_page.locator("[data-testid='add-series-search-form']").is_visible()
        assert authed_page.locator("[data-testid='add-series-search-input']").is_visible()
        assert authed_page.locator("[data-testid='add-series-sort-select']").is_visible()
        assert authed_page.locator("[data-testid='add-series-results']").is_visible()
        assert authed_page.locator("[data-testid='add-series-footer-dock']").is_visible()

        search_field_box = authed_page.locator(
            "[data-testid='add-series-search-field']"
        ).first.bounding_box()
        assert search_field_box is not None
        assert search_field_box["width"] >= 270

        add_title = authed_page.locator("[data-testid='add-series-title']").first
        add_gauge = authed_page.locator(
            "[data-testid='add-series-gauges'] .series-registry-gauge-ring"
        ).first

        add_title_style = add_title.evaluate(
            """
            node => {
              const style = window.getComputedStyle(node);
              return {
                fontSize: style.fontSize,
                fontWeight: style.fontWeight,
                letterSpacing: style.letterSpacing,
                lineHeight: style.lineHeight,
              };
            }
            """
        )
        add_gauge_box = add_gauge.bounding_box()

        assert add_gauge_box is not None

        authed_page.goto(f"{seeded_server}/series")
        authed_page.wait_for_load_state("networkidle")

        series_title = authed_page.locator("[data-testid='series-registry-title']").first
        series_gauge = authed_page.locator(
            "[data-testid='series-registry-gauges'] .series-registry-gauge-ring"
        ).first

        series_title_style = series_title.evaluate(
            """
            node => {
              const style = window.getComputedStyle(node);
              return {
                fontSize: style.fontSize,
                fontWeight: style.fontWeight,
                letterSpacing: style.letterSpacing,
                lineHeight: style.lineHeight,
              };
            }
            """
        )
        series_gauge_box = series_gauge.bounding_box()

        assert series_gauge_box is not None
        assert add_title_style == series_title_style
        assert abs(add_gauge_box["width"] - series_gauge_box["width"]) <= 1
        assert abs(add_gauge_box["height"] - series_gauge_box["height"]) <= 1

    def test_add_series_search_keeps_focus_through_remote_updates(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        request_count = {"value": 0}

        def fulfill_search(route) -> None:  # type: ignore[no-untyped-def]
            query = parse_qs(urlparse(route.request.url).query).get("q", [""])[0]
            if not query:
                route.continue_()
                return
            request_count["value"] += 1
            route.fulfill(
                status=200,
                content_type="text/html",
                body=f"""
<div id="add-series-results" data-testid="add-series-results">
  <div data-testid="add-series-result-card">{query}</div>
</div>
""",
            )

        authed_page.route("**/series/add**", fulfill_search)
        authed_page.goto(f"{seeded_server}/series/add")
        authed_page.wait_for_load_state("networkidle")

        search_input = authed_page.locator("[data-testid='add-series-search-input']").first
        search_input.click()

        authed_page.keyboard.type("B")
        authed_page.wait_for_timeout(350)
        wait_for_htmx(authed_page)
        assert search_input.evaluate("el => document.activeElement === el")

        authed_page.keyboard.type("a")
        authed_page.wait_for_timeout(350)
        wait_for_htmx(authed_page)
        assert search_input.evaluate("el => document.activeElement === el")

        authed_page.keyboard.press("Backspace")
        authed_page.wait_for_timeout(350)
        wait_for_htmx(authed_page)
        assert search_input.evaluate("el => document.activeElement === el")
        assert request_count["value"] >= 2

    def test_add_series_search_replaces_slow_inflight_responses(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        held_routes = []

        def fulfill_search(route) -> None:  # type: ignore[no-untyped-def]
            query = parse_qs(urlparse(route.request.url).query).get("q", [""])[0]
            if not query:
                route.continue_()
                return
            if query == "Batman":
                held_routes.append(route)
                return
            route.fulfill(
                status=200,
                content_type="text/html",
                body=f"""
<section id="add-series-results" data-testid="add-series-results" class="space-y-3">
  <div data-testid="add-series-results-list" class="add-series-results-list">
    <article data-testid="add-series-result-card">{query}</article>
  </div>
</section>
""",
            )

        authed_page.route("**/series/add**", fulfill_search)
        authed_page.goto(f"{seeded_server}/series/add")
        authed_page.wait_for_load_state("networkidle")

        search_input = authed_page.locator("[data-testid='add-series-search-input']").first
        search_input.fill("Batman")
        search_input.press("Enter")

        for _ in range(20):
            if held_routes:
                break
            authed_page.wait_for_timeout(50)
        assert held_routes

        authed_page.wait_for_function(
            """
            () => {
              const indicator = document.querySelector('[data-testid="add-series-results-loading"]');
              return indicator && Number(getComputedStyle(indicator).opacity) > 0;
            }
            """
        )

        search_input.fill("X-Men")
        search_input.press("Enter")
        authed_page.locator("[data-testid='add-series-result-card']").first.wait_for(
            state="visible",
            timeout=5000,
        )
        assert (
            authed_page.locator("[data-testid='add-series-result-card']").first.text_content()
            == "X-Men"
        )

        with suppress(Exception):
            held_routes.pop().fulfill(
                status=200,
                content_type="text/html",
                body="""
<section id="add-series-results" data-testid="add-series-results" class="space-y-3">
  <div data-testid="add-series-results-list" class="add-series-results-list">
    <article data-testid="add-series-result-card">Batman</article>
  </div>
</section>
""",
            )

        authed_page.wait_for_timeout(300)
        assert (
            authed_page.locator("[data-testid='add-series-result-card']").first.text_content()
            == "X-Men"
        )

    def test_add_series_preview_action_runs_full_search(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        requests_seen: list[tuple[str, str]] = []

        def fulfill_search(route) -> None:  # type: ignore[no-untyped-def]
            params = parse_qs(urlparse(route.request.url).query)
            query = params.get("q", [""])[0]
            mode = params.get("search_mode", [""])[0]
            if not query:
                route.continue_()
                return
            requests_seen.append((query, mode))
            if mode == "preview":
                route.fulfill(
                    status=200,
                    content_type="text/html",
                    body="""
<section id="add-series-results" data-testid="add-series-results" class="space-y-3">
  <div data-testid="add-series-preview-notice">
    <p>Quick preview</p>
    <a
      data-testid="add-series-full-search-button"
      href="/series/add?q=Batman&amp;sort=relevance"
      hx-get="/series/add?q=Batman&amp;sort=relevance"
      hx-target="#add-series-results"
      hx-swap="morph:outerHTML"
      hx-push-url="true"
      hx-sync="#add-series-search-form:replace"
      hx-indicator="#add-series-results-loading"
    >Search all ComicVine results</a>
  </div>
  <article data-testid="add-series-result-card">Batman preview</article>
</section>
""",
                )
                return
            route.fulfill(
                status=200,
                content_type="text/html",
                body="""
<section id="add-series-results" data-testid="add-series-results" class="space-y-3">
  <div data-testid="add-series-results-list" class="add-series-results-list">
    <article data-testid="add-series-result-card">Batman full search</article>
  </div>
</section>
""",
            )

        authed_page.route("**/series/add**", fulfill_search)
        authed_page.goto(f"{seeded_server}/series/add")
        authed_page.wait_for_load_state("networkidle")

        search_input = authed_page.locator("[data-testid='add-series-search-input']").first
        search_input.fill("Batman")

        authed_page.locator("[data-testid='add-series-preview-notice']").wait_for(
            state="visible",
            timeout=5000,
        )
        authed_page.locator("[data-testid='add-series-full-search-button']").click()

        expect(authed_page.locator("[data-testid='add-series-result-card']").first).to_have_text(
            "Batman full search", timeout=5000
        )
        assert ("Batman", "preview") in requests_seen
        assert ("Batman", "") in requests_seen

    def test_add_series_footer_pagination_advances_results_and_url(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        def fulfill_search(route) -> None:  # type: ignore[no-untyped-def]
            params = parse_qs(urlparse(route.request.url).query)
            query = params.get("q", [""])[0]
            page = int(params.get("page", ["1"])[0])
            if not query:
                route.continue_()
                return

            body = f"""
<div id="add-series-header-metrics" data-testid="add-series-header-metrics" class="add-series-header-metrics" hx-swap-oob="outerHTML"></div>
<div id="page-footer-dock" data-testid="page-footer-dock" hx-swap-oob="innerHTML">
  <div data-testid="add-series-footer-dock">
    <div class="page-dock-inner" data-testid="page-dock-inner">
      <div class="page-dock-pagination" data-testid="page-dock-pagination">
        <nav aria-label="Pagination" class="flex items-center justify-center gap-1" hx-boost="false">
          <button
            type="button"
            data-page-url="/series/add?q=Batman&page={"2" if page == 1 else "1"}"
            data-testid="series-pagination-{"next" if page == 1 else "prev"}"
            hx-get="/series/add?q=Batman&page={"2" if page == 1 else "1"}"
            hx-target="#add-series-results"
            hx-swap="outerHTML show:#content:top"
            hx-push-url="true"
            class="px-3 py-2 rounded-md text-sm font-medium text-pb-text-sec hover:bg-pb-card-hover transition-colors"
          >
            {"Next »" if page == 1 else "« Prev"}
          </button>
        </nav>
      </div>
      <div class="page-dock-status" data-testid="page-dock-status"></div>
    </div>
  </div>
</div>
<section id="add-series-results" data-testid="add-series-results" class="space-y-3">
  <div data-testid="add-series-results-list" class="add-series-results-list">
    <article data-testid="add-series-result-card">{query} page {page}</article>
    <div style="height: 1600px;" aria-hidden="true"></div>
  </div>
</section>
"""
            route.fulfill(status=200, content_type="text/html", body=body)

        authed_page.route("**/series/add**", fulfill_search)
        authed_page.goto(f"{seeded_server}/series/add")
        authed_page.wait_for_load_state("networkidle")

        search_input = authed_page.locator("[data-testid='add-series-search-input']").first
        search_input.fill("Batman")
        authed_page.wait_for_timeout(350)
        wait_for_htmx(authed_page)

        assert (
            authed_page.locator("[data-testid='add-series-result-card']").first.text_content()
            == "Batman page 1"
        )
        authed_page.evaluate(
            """
            () => {
              const content = document.querySelector('#content');
              content.scrollTop = content.scrollHeight;
            }
            """
        )
        assert authed_page.evaluate("() => document.querySelector('#content').scrollTop") > 0

        authed_page.locator("[data-testid='series-pagination-next']").click()
        wait_for_htmx(authed_page)

        assert (
            authed_page.locator("[data-testid='add-series-result-card']").first.text_content()
            == "Batman page 2"
        )
        authed_page.wait_for_function(
            "() => document.querySelector('#content').scrollTop === 0",
            timeout=1000,
        )
        assert "page=2" in authed_page.url

    def test_add_series_footer_pagination_buttons_share_typography_contract(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        def fulfill_search(route) -> None:  # type: ignore[no-untyped-def]
            query = parse_qs(urlparse(route.request.url).query).get("q", [""])[0]
            if not query:
                route.continue_()
                return

            route.fulfill(
                status=200,
                content_type="text/html",
                body="""
<div id="add-series-header-metrics" data-testid="add-series-header-metrics" class="add-series-header-metrics" hx-swap-oob="outerHTML"></div>
<div id="page-footer-dock" data-testid="page-footer-dock" hx-swap-oob="innerHTML">
  <div data-testid="add-series-footer-dock">
    <div class="page-dock-inner" data-testid="page-dock-inner">
      <div class="page-dock-pagination" data-testid="page-dock-pagination">
        <nav aria-label="Pagination" class="flex items-center justify-center gap-1" hx-boost="false">
          <button
            type="button"
            id="pagination-prev"
            data-page-url="/series/add?q=Batman&page=1"
            data-testid="series-pagination-prev"
            hx-get="/series/add?q=Batman&page=1"
            hx-target="#add-series-results"
            hx-swap="outerHTML show:#content:top"
            hx-push-url="true"
            class="px-3 py-2 rounded-md text-sm font-medium text-pb-text-sec hover:bg-pb-card-hover transition-colors"
          >
            &laquo; Prev
          </button>
          <button
            type="button"
            id="pagination-page-1"
            data-testid="series-pagination-page-1"
            data-page-url="/series/add?q=Batman&page=1"
            hx-get="/series/add?q=Batman&page=1"
            hx-target="#add-series-results"
            hx-swap="outerHTML show:#content:top"
            hx-push-url="true"
            class="px-3 py-2 rounded-md text-sm font-medium text-pb-text-sec hover:bg-pb-card-hover transition-colors"
          >
            1
          </button>
          <span id="pagination-page-2" class="px-3 py-2 rounded-md text-sm font-medium bg-pb-interactive text-white">2</span>
          <button
            type="button"
            id="pagination-next"
            data-page-url="/series/add?q=Batman&page=3"
            data-testid="series-pagination-next"
            hx-get="/series/add?q=Batman&page=3"
            hx-target="#add-series-results"
            hx-swap="outerHTML show:#content:top"
            hx-push-url="true"
            class="px-3 py-2 rounded-md text-sm font-medium text-pb-text-sec hover:bg-pb-card-hover transition-colors"
          >
            Next &raquo;
          </button>
        </nav>
      </div>
      <div class="page-dock-status" data-testid="page-dock-status"></div>
    </div>
  </div>
</div>
<section id="add-series-results" data-testid="add-series-results" class="space-y-3">
  <div data-testid="add-series-results-list" class="add-series-results-list">
    <article data-testid="add-series-result-card">Batman page 2</article>
  </div>
</section>
""",
            )

        authed_page.route("**/series/add**", fulfill_search)
        authed_page.goto(f"{seeded_server}/series/add")
        authed_page.wait_for_load_state("networkidle")

        search_input = authed_page.locator("[data-testid='add-series-search-input']").first
        search_input.fill("Batman")
        authed_page.wait_for_timeout(350)
        wait_for_htmx(authed_page)

        prev_button = authed_page.locator("[data-testid='series-pagination-prev']").first
        page_token = authed_page.locator("[data-testid='series-pagination-page-1']").first
        current_page = authed_page.locator("#pagination-page-2").first
        next_button = authed_page.locator("[data-testid='series-pagination-next']").first

        def read_typography(locator) -> dict[str, str]:  # type: ignore[no-untyped-def]
            return locator.evaluate(
                """
                node => {
                  const style = window.getComputedStyle(node);
                  return {
                    fontFamily: style.fontFamily,
                    fontSize: style.fontSize,
                    fontWeight: style.fontWeight,
                    lineHeight: style.lineHeight,
                  };
                }
                """
            )

        prev_typography = read_typography(prev_button)
        page_typography = read_typography(page_token)
        current_typography = read_typography(current_page)
        next_typography = read_typography(next_button)

        assert page_typography == prev_typography
        assert current_typography == prev_typography
        assert next_typography == prev_typography

    def test_add_series_modal_uses_full_backdrop_and_read_only_library_settings(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        authed_page.set_viewport_size({"width": 1440, "height": 1100})
        authed_page.goto(f"{seeded_server}/series/add")
        authed_page.wait_for_load_state("networkidle")

        authed_page.evaluate(
            """
            () => {
              selectResult({
                id: 12345,
                title: "Ultimate Spider-Man",
                publisher: "Marvel",
                year: 2024,
                issueCount: 14,
                coverUrl: "",
                description: "Test description"
              });
            }
            """
        )

        modal = authed_page.locator(".modal-shell").first
        backdrop = authed_page.locator(".modal-backdrop").first
        root_field = authed_page.locator("[data-testid='add-series-root-display']").first
        folder_preview = authed_page.locator("[data-testid='add-series-folder-preview']").first

        modal.wait_for(state="visible", timeout=5000)
        backdrop_box = backdrop.bounding_box()

        assert backdrop_box is not None
        assert backdrop_box["y"] <= 1
        assert backdrop_box["height"] >= 1098
        assert root_field.is_disabled()
        assert "Comics Directory" in (root_field.input_value() or "")
        assert "/" not in (folder_preview.text_content() or "")
        assert (folder_preview.text_content() or "").strip() == "Ultimate Spider-Man (2024)"
        for theme in ("dark", "light"):
            authed_page.evaluate("(value) => applyTheme(value)", theme)
            authed_page.wait_for_timeout(50)
            assert (folder_preview.text_content() or "").strip() == "Ultimate Spider-Man (2024)"
