"""Focused browser coverage for the tabbed post-processing page."""

from __future__ import annotations

import pytest

from tests.e2e.pages.post_processing import PostProcessingPage

pytestmark = pytest.mark.e2e


class TestPostProcessingPage:
    """Behavior-first E2E checks for the post-processing shell."""

    def test_post_processing_renders_stable_shell(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        post_processing = PostProcessingPage(authed_page, seeded_server)
        post_processing.goto()

        assert post_processing.page_root.is_visible()
        assert post_processing.shell.is_visible()
        assert post_processing.header.is_visible()
        assert post_processing.gauges.is_visible()
        assert post_processing.tabs.is_visible()
        assert post_processing.content.is_visible()
        assert post_processing.queue_panel.is_visible()
        assert post_processing.footer_dock.is_visible()
        assert post_processing.queue_active_section.is_visible()
        assert post_processing.queue_imported_section.is_visible()
        assert post_processing.queue_empty.is_visible()
        assert post_processing.queue_imported_empty.is_visible()
        assert post_processing.tab("queue").get_attribute("aria-current") == "page"
        assert "No active imports" in (authed_page.text_content("body") or "")

    def test_post_processing_tab_filter_search_and_sort_keep_shell_stable(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        post_processing = PostProcessingPage(authed_page, seeded_server)
        post_processing.goto(tab="history")

        assert post_processing.tab("history").get_attribute("aria-current") == "page"
        assert post_processing.history_panel.is_visible()
        assert post_processing.history_toolbar.is_visible()
        assert post_processing.footer_dock.is_visible()
        assert post_processing.history_item("Batman 001 (2016) [Digital].cbz").is_visible()

        post_processing.apply_result_filter("failed")

        assert post_processing.page_root.is_visible()
        assert authed_page.locator("[data-testid='post-processing-content']").count() == 1
        assert post_processing.history_empty.is_visible()

        post_processing.apply_result_filter("imported")
        assert post_processing.history_item("Batman 001 (2016) [Digital].cbz").is_visible()

        post_processing.apply_client_filter("sabnzbd")
        assert post_processing.history_item("Batman 001 (2016) [Digital].cbz").is_visible()

        post_processing.search_history("Batman")
        assert post_processing.history_item("Batman 001 (2016) [Digital].cbz").is_visible()

        post_processing.sort_history("title")
        assert post_processing.page_root.is_visible()
        assert authed_page.locator("[data-testid='pp-history-panel']").count() == 1

    def test_post_processing_history_wrapper_allows_filter_panels_to_escape_table_bounds(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        post_processing = PostProcessingPage(authed_page, seeded_server)
        post_processing.goto(tab="history")

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

    def test_post_processing_queue_details_toggle(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        post_processing = PostProcessingPage(authed_page, seeded_server)
        post_processing.goto()

        authed_page.route(
            "**/htmx/post-processing/queue",
            lambda route: route.fulfill(
                status=200,
                content_type="text/html",
                body="""
<section
  id="post-processing-content"
  data-testid="post-processing-content"
  class="downloads-view"
  hx-get="/htmx/post-processing/queue"
  hx-trigger="every 2s [window.postProcessingQueueRefreshEnabled()], post-processing:refresh from:body"
  hx-target="#post-processing-content"
  hx-swap="outerHTML"
>
  <div data-testid="post-processing-header" class="downloads-header">
    <div data-testid="pp-gauges" class="downloads-gauges"></div>
  </div>
  <div data-testid="pp-queue-panel" class="downloads-panel-stack">
    <section data-testid="pp-queue-active-section" class="downloads-section">
      <div class="downloads-table-wrap">
        <table data-testid="pp-queue-active-table" class="downloads-table">
          <tbody x-data="{ expanded: false }">
            <tr data-testid="pp-queue-item">
              <td>Active Transfer.cbz</td>
              <td>
                <button
                  type="button"
                  data-testid="pp-queue-item-details-toggle"
                  class="downloads-action-btn"
                  @click="expanded = !expanded"
                  :aria-expanded="expanded ? 'true' : 'false'"
                  aria-label="Toggle details"
                >
                  <svg class="transition-transform" :class="expanded && 'rotate-180'" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7"/>
                  </svg>
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</section>
""",
            ),
        )

        authed_page.evaluate("() => htmx.trigger(document.body, 'post-processing:refresh')")
        post_processing.wait_for_htmx()

        assert post_processing.queue_items.count() == 1
        post_processing.queue_items.first.hover()
        assert authed_page.evaluate("() => window.postProcessingQueueRefreshEnabled()") is False
        authed_page.mouse.move(4, 4)
        authed_page.wait_for_timeout(100)
        assert authed_page.evaluate("() => window.postProcessingQueueRefreshEnabled()") is True

        toggle = post_processing.queue_details_toggle
        assert toggle.get_attribute("aria-expanded") == "false"

        toggle.click()

        assert toggle.get_attribute("aria-expanded") == "true"
        assert toggle.get_attribute("aria-label") == "Toggle details"

    def test_post_processing_queue_live_status_updates_on_refresh(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        post_processing = PostProcessingPage(authed_page, seeded_server)
        post_processing.goto()

        responses = iter(
            [
                """
<section
  id="post-processing-content"
  data-testid="post-processing-content"
  class="downloads-view"
  hx-get="/htmx/post-processing/queue"
  hx-trigger="every 2s [window.postProcessingQueueRefreshEnabled()], post-processing:refresh from:body"
  hx-target="#post-processing-content"
  hx-swap="outerHTML"
>
  <div data-testid="post-processing-header" class="downloads-header">
    <div data-testid="pp-gauges" class="downloads-gauges"></div>
  </div>
  <div data-testid="pp-queue-panel" class="downloads-panel-stack">
    <section data-testid="pp-queue-active-section" class="downloads-section">
      <div class="downloads-table-wrap">
        <table data-testid="pp-queue-active-table" class="downloads-table">
          <tbody x-data="{ expanded: false }">
            <tr data-testid="pp-queue-item">
              <td>Active Transfer.cbz</td>
              <td><span data-testid="pp-queue-item-phase" class="pill pill-warning">Transferring</span></td>
              <td data-testid="pp-queue-item-progress-summary">62% · 1.2 GB / 2.0 GB</td>
              <td data-testid="pp-queue-item-speed">50.0 MB/s</td>
              <td data-testid="pp-queue-item-time">15s left</td>
              <td>
                <div class="downloads-progress-track">
                  <span data-testid="pp-queue-item-progress-bar" class="downloads-progress-fill is-amber" style="width: 62.5%"></span>
                </div>
              </td>
              <td>
                <button type="button" data-testid="pp-queue-item-details-toggle" class="downloads-action-btn" :aria-expanded="expanded ? 'true' : 'false'" @click="expanded = !expanded" aria-label="Toggle details">
                  <svg class="transition-transform" :class="expanded && 'rotate-180'" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7"/>
                  </svg>
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
    <section data-testid="pp-queue-imported-section" class="downloads-section">
      <div data-testid="pp-queue-imported-empty"></div>
    </section>
  </div>
</section>
""",
                """
<section
  id="post-processing-content"
  data-testid="post-processing-content"
  class="downloads-view"
  hx-get="/htmx/post-processing/queue"
  hx-trigger="every 2s [window.postProcessingQueueRefreshEnabled()], post-processing:refresh from:body"
  hx-target="#post-processing-content"
  hx-swap="outerHTML"
>
  <div data-testid="post-processing-header" class="downloads-header">
    <div data-testid="pp-gauges" class="downloads-gauges"></div>
  </div>
  <div data-testid="pp-queue-panel" class="downloads-panel-stack">
    <section data-testid="pp-queue-active-section" class="downloads-section">
      <div class="downloads-table-wrap">
        <table data-testid="pp-queue-active-table" class="downloads-table">
          <tbody x-data="{ expanded: false }">
            <tr data-testid="pp-queue-item">
              <td>Active Transfer.cbz</td>
              <td><span data-testid="pp-queue-item-phase" class="pill pill-warning">Registering library file</span></td>
              <td>
                <div class="downloads-progress-track">
                  <span data-testid="pp-queue-item-progress-bar" class="downloads-progress-fill is-blue" style="width: 92%"></span>
                </div>
                <span data-testid="pp-queue-item-progress-summary">Step 5 of 5</span>
              </td>
              <td data-testid="pp-queue-item-speed">—</td>
              <td data-testid="pp-queue-item-time">7s elapsed</td>
              <td>
                <button type="button" data-testid="pp-queue-item-details-toggle" class="downloads-action-btn" :aria-expanded="expanded ? 'true' : 'false'" @click="expanded = !expanded" aria-label="Toggle details">
                  <svg class="transition-transform" :class="expanded && 'rotate-180'" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7"/>
                  </svg>
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
    <section data-testid="pp-queue-imported-section" class="downloads-section">
      <div data-testid="pp-queue-imported-empty"></div>
    </section>
  </div>
</section>
""",
            ]
        )

        last_body = {"value": ""}

        def fulfill_queue(route) -> None:  # type: ignore[no-untyped-def]
            body = next(responses, last_body["value"])
            last_body["value"] = body
            route.fulfill(status=200, content_type="text/html", body=body)

        authed_page.route("**/htmx/post-processing/queue", fulfill_queue)

        authed_page.evaluate("() => htmx.trigger(document.body, 'post-processing:refresh')")
        post_processing.wait_for_htmx()
        assert authed_page.locator("text=62% · 1.2 GB / 2.0 GB").first.is_visible()
        assert authed_page.locator("text=50.0 MB/s").first.is_visible()
        assert authed_page.locator("text=15s left").first.is_visible()
        assert authed_page.locator("text=Transferring").first.is_visible()
        assert post_processing.queue_details_toggle.get_attribute("aria-label") == "Toggle details"

        authed_page.evaluate("() => htmx.trigger(document.body, 'post-processing:refresh')")
        post_processing.wait_for_htmx()
        assert authed_page.locator("text=Step 5 of 5").first.is_visible()
        assert authed_page.locator("text=7s elapsed").first.is_visible()
        assert authed_page.locator("text=Registering library file").first.is_visible()
        assert post_processing.queue_details_toggle.get_attribute("aria-label") == "Toggle details"

    def test_post_processing_history_refresh_and_actions_keep_shell_stable(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        post_processing = PostProcessingPage(authed_page, seeded_server)
        post_processing.goto(tab="history")

        authed_page.evaluate(
            """() => {
                htmx.ajax('GET', '/htmx/post-processing/history?result=all&client=&search=&sort=-completed_at&page=1', {
                    target: '#pp-history-results',
                    swap: 'outerHTML'
                });
            }"""
        )
        post_processing.wait_for_htmx()

        assert post_processing.page_root.is_visible()
        assert authed_page.locator("[data-testid='pp-history-panel']").count() == 1
        assert post_processing.history_toolbar.is_visible()
        assert post_processing.history_item("Batman 001 (2016) [Digital].cbz").is_visible()
        assert post_processing.history_clear_button.is_visible()
        assert post_processing.history_remove_button().is_visible()

    def test_post_processing_history_poll_preserves_active_filters(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        post_processing = PostProcessingPage(authed_page, seeded_server)
        post_processing.goto(tab="history")

        post_processing.apply_result_filter("failed")

        assert post_processing.history_empty.is_visible()
        assert "result=failed" in (
            authed_page.locator("[data-testid='pp-history-results']").first.get_attribute("hx-get")
            or ""
        )

        authed_page.evaluate(
            """() => {
                const target = document.querySelector('#pp-history-results');
                if (!target) throw new Error('post-processing history results missing');
                htmx.trigger(target, 'refresh');
            }"""
        )
        post_processing.wait_for_htmx()

        assert post_processing.history_empty.is_visible()
        assert authed_page.locator("[data-testid='pp-history-table']").count() == 0
