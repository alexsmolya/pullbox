"""Focused E2E coverage for the issue detail rewrite."""

from __future__ import annotations

import json

import pytest

from tests.e2e.pages.issue_detail import IssueDetailPage

pytestmark = pytest.mark.e2e


class TestIssueDetailPage:
    """Behavior-first E2E coverage for /issues/{id}."""

    def test_copy_path_tooltip_renders_on_hover(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        issue = IssueDetailPage(authed_page, seeded_server)
        issue.goto(1)

        issue.library_file_copy.hover()

        assert issue.library_file_copy.get_attribute("data-tip") == "Copy path"

    def test_initial_load_renders_stable_issue_shell(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        issue = IssueDetailPage(authed_page, seeded_server)
        issue.goto(1)

        header_box = authed_page.locator("[data-testid='app-header']").bounding_box()
        hero_box = issue.hero.bounding_box()

        assert header_box is not None
        assert hero_box is not None
        assert issue.page_shell.is_visible()
        assert issue.back_link.is_visible()
        assert issue.hero.is_visible()
        assert issue.hero_summary_panel.is_visible()
        title_link = authed_page.locator("[data-testid='issue-detail-title-link']").first
        assert title_link.is_visible()
        assert title_link.get_attribute("href") == (
            "https://comicvine.gamespot.com/batman-1/4000-50001/"
        )
        assert title_link.get_attribute("target") == "_blank"
        assert issue.hero_actions_panel.is_visible()
        actions_title = authed_page.locator("[data-testid='issue-detail-actions-title']").first
        assert actions_title.inner_text().lower() == "manage issue"
        download_box = authed_page.locator(
            "[data-testid='issue-action-download']"
        ).first.bounding_box()
        manual_search_box = authed_page.locator(
            "[data-testid='issue-action-manual-search']"
        ).first.bounding_box()
        assert download_box is not None
        assert manual_search_box is not None
        assert abs(download_box["width"] - manual_search_box["width"]) <= 2
        action_gaps = authed_page.evaluate(
            """() => [
                getComputedStyle(document.querySelector("[data-testid='issue-action-download']")).gap,
                getComputedStyle(document.querySelector("[data-testid='issue-action-manual-search']")).gap,
            ]"""
        )
        assert action_gaps == ["8px", "8px"]
        assert issue.page.locator("[data-testid='issue-action-manual-search']").first.is_visible()
        assert not issue.search_region.is_visible()
        assert issue.description_section.is_visible()
        assert issue.description_title.is_visible()
        assert issue.creators_section.is_visible()
        assert issue.creators_title.is_visible()
        assert issue.library_file_section.is_visible()
        assert issue.library_file_title.is_visible()
        assert issue.library_file_copy.is_visible()
        assert issue.footer.is_visible()
        assert authed_page.locator("[data-testid='issue-detail-telemetry-strip']").count() == 0
        assert hero_box["y"] >= header_box["y"] + header_box["height"] + 12

    def test_back_link_returns_to_series_detail_without_shell_blank(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        issue = IssueDetailPage(authed_page, seeded_server)
        issue.goto(1)

        issue.open_back_link()

        assert "/series/" in authed_page.url
        assert authed_page.locator("[data-testid='page-footer-dock']").first.is_visible()
        assert authed_page.locator("h1, h2").filter(has_text="Batman").first.is_visible()

    def test_tab_switch_keeps_issue_detail_content_visible(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        issue = IssueDetailPage(authed_page, seeded_server)
        issue.goto(1)

        issue.round_trip_tab_visibility()

        assert issue.page_shell.is_visible()
        assert issue.hero.is_visible()
        assert issue.description_section.is_visible()
        assert issue.footer.is_visible()
        assert (
            authed_page.locator("#content").first.get_attribute("data-detail-history-hidden")
            is None
        )

    def test_status_row_uses_shared_pill_contracts(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        issue = IssueDetailPage(authed_page, seeded_server)
        issue.goto(1)

        status_contract = authed_page.evaluate(
            """() => {
                const row = document.querySelector("[data-testid='issue-detail-status-row']");
                const pills = row ? Array.from(row.querySelectorAll(".pill")) : [];
                const first = pills[0];
                if (!first) {
                    return {
                        count: pills.length,
                        firstBackground: null,
                        firstFontFamily: null,
                    };
                }
                const firstStyle = window.getComputedStyle(first);
                return {
                    count: pills.length,
                    firstBackground: firstStyle.backgroundColor,
                    firstFontFamily: firstStyle.fontFamily,
                };
            }"""
        )

        assert status_contract["count"] >= 4
        assert status_contract["firstBackground"] not in ("rgba(0, 0, 0, 0)", "transparent")
        assert "DM Sans" in status_contract["firstFontFamily"]

    def test_sections_share_a_wider_aligned_content_width(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        authed_page.set_viewport_size({"width": 1600, "height": 1200})
        issue = IssueDetailPage(authed_page, seeded_server)
        issue.goto(1)

        geometry = authed_page.evaluate(
            """() => {
                const hero = document.querySelector("[data-testid='issue-detail-hero']");
                const actions = document.querySelector("[data-testid='issue-detail-hero-actions-panel']");
                const sections = [
                    document.querySelector("[data-testid='issue-description-section']"),
                    document.querySelector("[data-testid='issue-creators-section']"),
                    document.querySelector("[data-testid='issue-library-file-section']"),
                ];
                const rectFor = (el) => {
                    if (!el) return null;
                    const rect = el.getBoundingClientRect();
                    return { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom, width: rect.width };
                };
                return {
                    hero: rectFor(hero),
                    actions: rectFor(actions),
                    sections: sections.map(rectFor),
                    actionsParentTestId: actions?.closest("[data-testid='issue-detail-hero']")?.dataset.testid || null,
                };
            }"""
        )

        assert geometry["hero"] is not None
        assert geometry["actions"] is not None
        assert all(rect is not None for rect in geometry["sections"])
        assert geometry["actionsParentTestId"] == "issue-detail-hero"
        lefts = [geometry["hero"]["left"], *(rect["left"] for rect in geometry["sections"])]
        rights = [geometry["hero"]["right"], *(rect["right"] for rect in geometry["sections"])]
        widths = [geometry["hero"]["width"], *(rect["width"] for rect in geometry["sections"])]
        assert max(lefts) - min(lefts) <= 2
        assert max(rights) - min(rights) <= 2
        assert min(widths) >= 1200
        assert geometry["actions"]["left"] > geometry["hero"]["left"] + 330
        assert geometry["actions"]["right"] <= geometry["hero"]["right"] + 1
        assert geometry["actions"]["top"] >= geometry["hero"]["top"]
        assert geometry["actions"]["bottom"] <= geometry["hero"]["bottom"]

    def test_wanted_issue_import_file_browser_opens_without_disturbing_shell(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        issue = IssueDetailPage(authed_page, seeded_server)
        issue.goto(2)

        authed_page.route(
            "**/api/v1/filesystem/browse?**",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "path": "/tmp/imports",
                        "parent": "/tmp",
                        "directories": [],
                        "files": [
                            {
                                "name": "Batman 002.cbz",
                                "path": "/tmp/imports/Batman 002.cbz",
                                "size": 52428800,
                            }
                        ],
                        "quick_links": [],
                    }
                ),
            ),
        )

        assert issue.hero_actions_panel.is_visible()
        issue.open_import_file_browser()

        assert issue.page_shell.is_visible()
        assert issue.hero.is_visible()
        assert issue.hero_actions_panel.is_visible()
        assert issue.file_browser_modal.is_visible()
        assert issue.import_modal.is_visible() is False

        issue.close_file_browser()

        assert issue.page_shell.is_visible()
        assert issue.hero_actions_panel.is_visible()
        assert issue.footer.is_visible()

    def test_wanted_issue_import_selection_opens_live_progress_modal(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        issue = IssueDetailPage(authed_page, seeded_server)
        issue.goto(2)

        authed_page.route(
            "**/api/v1/filesystem/browse?**",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "path": "/tmp/imports",
                        "parent": "/tmp",
                        "directories": [],
                        "files": [
                            {
                                "name": "Batman 002.cbz",
                                "path": "/tmp/imports/Batman 002.cbz",
                                "size": 52428800,
                            }
                        ],
                        "quick_links": [],
                    }
                ),
            ),
        )

        def handle_import_start(route) -> None:  # type: ignore[no-untyped-def]
            route.fulfill(
                status=202,
                content_type="application/json",
                body=json.dumps(
                    {
                        "issue_id": 2,
                        "state": "running",
                        "message": "Preparing import...",
                        "current_file_name": "Batman 002.cbz",
                        "current_file_stage": "preparing",
                        "current_file_progress_current": 0,
                        "current_file_progress_total": 1,
                        "current_file_progress_pct": 0,
                        "current_file_progress_unit": "steps",
                        "file_index": 1,
                        "total_files": 1,
                    }
                ),
            )

        authed_page.route("**/api/v1/issues/2/import-file/start", handle_import_start)
        authed_page.route(
            "**/api/v1/issues/2/import-file/progress",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "issue_id": 2,
                        "state": "running",
                        "message": "Importing selected file...",
                        "current_file_name": "Batman 002.cbz",
                        "current_file_stage": "transferring",
                        "current_file_progress_current": 26214400,
                        "current_file_progress_total": 52428800,
                        "current_file_progress_pct": 50,
                        "current_file_progress_unit": "bytes",
                        "file_index": 1,
                        "total_files": 1,
                    }
                ),
            ),
        )

        issue.open_import_file_browser()
        with authed_page.expect_request("**/api/v1/issues/2/import-file/start") as request_info:
            authed_page.locator("[data-testid='file-browser-file-entry']").first.click()

        assert request_info.value.post_data_json == {
            "allow_resource_safety_exception": False,
            "file_path": "/tmp/imports/Batman 002.cbz",
            "move_to_library": True,
        }
        issue.import_modal.wait_for(state="visible", timeout=5000)
        assert authed_page.locator("[data-testid='issue-import-progress-bar']").first.is_visible()
        assert authed_page.locator("[data-testid='issue-import-progress-value']").first.is_visible()

    def test_manual_search_block_posts_to_blocklist(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        issue = IssueDetailPage(authed_page, seeded_server)
        issue.goto(2)

        authed_page.evaluate("() => { window.pbConfirm = async () => true; }")

        authed_page.route(
            "**/htmx/issues/2/search-results",
            lambda route: route.fulfill(
                status=200,
                content_type="text/html",
                body="""
<div data-testid="issue-search-results">
  <table class="downloads-table issue-search-results-table">
    <tbody id="issue-search-results-body">
      <tr>
        <td class="is-right" x-data="{ grabbing: false, blocking: false, blocked: false, blockRelease(btn) { if (this.grabbing || this.blocking || this.blocked) return; pbConfirm({ title: 'Block Release', message: 'Add this release to the blocklist? It won\\'t appear in future search results.', confirmText: 'Block' }).then((ok) => { if (!ok) return; this.blocking = true; fetch('/api/v1/blocklist', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': 'test-csrf' }, body: JSON.stringify({ release_title: btn.dataset.blockTitle, series_id: 1, issue_id: 2 }) }).then((response) => response.json().catch(() => ({})).then((data) => ({ response, data }))).then(({ response, data }) => { const detail = data.detail?.error?.message || data.detail || data.error?.message || ''; const alreadyBlocked = response.status === 409 && String(detail).toLowerCase().includes('already in blocklist'); if (!response.ok && !alreadyBlocked) { throw new Error(detail || 'Failed to block release.'); } this.blocked = true; }).finally(() => { this.blocking = false; }); }); } }">
          <div class="issue-search-action-row">
            <button
              x-show="!blocked"
              data-block-title="Batman.018.2026.Digital.Zone-Empire"
              @click="blockRelease($el)"
              class="chip-btn chip-btn-sm chip-btn-error cursor-pointer"
            >
              Block
            </button>
            <span x-show="blocked" x-cloak class="pill pill-error opacity-60">Blocked</span>
          </div>
        </td>
      </tr>
    </tbody>
  </table>
</div>
""",
            ),
        )

        authed_page.route(
            "**/api/v1/blocklist",
            lambda route: route.fulfill(
                status=201,
                content_type="application/json",
                body=json.dumps(
                    {
                        "id": 1,
                        "release_title": "Batman.018.2026.Digital.Zone-Empire",
                        "release_title_normalized": "batman.018.2026.digital.zone-empire",
                        "download_url": None,
                        "series_id": 1,
                        "issue_id": 2,
                        "indexer_id": None,
                        "reason": "manual",
                        "error_message": None,
                        "release_group": None,
                        "download_history_id": None,
                        "series_title": "Batman",
                        "created_at": "2026-05-02T20:00:00Z",
                        "updated_at": "2026-05-02T20:00:00Z",
                    }
                ),
            ),
        )

        issue.run_manual_search()

        with authed_page.expect_request("**/api/v1/blocklist") as request_info:
            issue.search_region.locator("button", has_text="Block").first.click()

        payload = json.loads(request_info.value.post_data or "{}")
        assert payload == {
            "release_title": "Batman.018.2026.Digital.Zone-Empire",
            "series_id": 1,
            "issue_id": 2,
        }
        issue.search_region.locator("text=Blocked").first.wait_for(state="visible", timeout=5000)

    def test_manual_search_modal_opens_without_disturbing_shell(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        issue = IssueDetailPage(authed_page, seeded_server)
        issue.goto(1)

        issue.run_manual_search()

        assert issue.page_shell.is_visible()
        assert issue.hero.is_visible()
        assert issue.search_region.is_visible()

    def test_tab_switch_preserves_active_issue_manual_search(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        issue = IssueDetailPage(authed_page, seeded_server)
        issue.goto(1)

        issue.run_manual_search()
        issue.round_trip_tab_visibility()

        assert issue.page_shell.is_visible()
        assert issue.hero.is_visible()
        assert issue.search_region.is_visible()
        assert issue.search_results.is_visible() or issue.search_results_empty_state.is_visible()
        assert (
            authed_page.locator("#content").first.get_attribute("data-detail-history-hidden")
            is None
        )
        assert issue.search_results.is_visible() or issue.search_results_empty_state.is_visible()
        assert authed_page.locator("[data-testid='issue-search-modal-footer-close']").is_visible()
        assert issue.footer.is_visible()

        issue.close_manual_search()

        assert issue.page_shell.is_visible()
        assert issue.footer.is_visible()

    def test_manual_search_modal_fits_action_controls_without_clipping(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        authed_page.set_viewport_size({"width": 1600, "height": 1200})
        issue = IssueDetailPage(authed_page, seeded_server)
        issue.goto(1)

        issue.run_manual_search()

        modal_box = issue.search_region.locator(".issue-search-modal-panel").first.bounding_box()
        action_rows = issue.search_results.locator(".issue-search-action-row")

        assert modal_box is not None
        assert modal_box["width"] >= 1180
        if action_rows.count() > 0:
            action_box = action_rows.first.bounding_box()
            assert action_box is not None
            assert (action_box["x"] + action_box["width"]) <= (
                modal_box["x"] + modal_box["width"] - 12
            )

    def test_skipped_issue_can_be_marked_wanted_from_detail_page(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        issue = IssueDetailPage(authed_page, seeded_server)
        issue.goto(3)

        assert authed_page.locator("[data-testid='issue-action-toggle']").first.text_content()
        assert "Skipped" in (issue.status_row.text_content() or "")
        issue.toggle_status()

        assert "Wanted" in (issue.status_row.text_content() or "")
        assert authed_page.locator("[data-testid='issue-action-search']").first.is_visible()
        assert "Mark Skipped" in (
            authed_page.locator("[data-testid='issue-action-toggle']").first.text_content() or ""
        )
