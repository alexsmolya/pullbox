"""Focused browser coverage for the standardized library page."""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import expect

from tests.e2e.pages.library import LibraryPage

pytestmark = pytest.mark.e2e


class TestLibraryPage:
    """Behavior-first E2E checks for the library shell."""

    def test_library_renders_stable_regions(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        library = LibraryPage(authed_page, seeded_server)
        library.goto()

        assert library.page_root.is_visible()
        assert library.directory_panel.is_visible()
        assert library.stats_grid.is_visible()
        assert library.stat_card("total-files").is_visible()
        assert library.stat_card("matched-files").is_visible()
        assert library.stat_card("unmatched-files").is_visible()
        assert library.stat_card("storage-used").is_visible()
        assert library.matching_banner.is_visible()
        assert library.footer_strip.is_visible()

    def test_library_tree_header_aligns_with_details_toolbar_and_stays_sticky(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        review_root = Path("/tmp/pullbox-e2e-library")
        seeded_dirs = [review_root / f"zz-alignment-{index:02d}" for index in range(18)]
        for path in seeded_dirs:
            path.mkdir(exist_ok=True)
        try:
            library = LibraryPage(authed_page, seeded_server)
            library.goto()

            tree_header_box = library.tree_header.bounding_box()
            toolbar_box = library.browser_toolbar.bounding_box()
            assert tree_header_box is not None
            assert toolbar_box is not None
            assert abs(tree_header_box["y"] - toolbar_box["y"]) <= 1.0
            assert round(tree_header_box["height"]) == round(toolbar_box["height"])

            initial_top = tree_header_box["y"]
            library.tree_list.evaluate("(node) => { node.scrollTop = node.scrollHeight; }")
            authed_page.wait_for_timeout(150)

            scrolled_tree_header_box = library.tree_header.bounding_box()
            assert scrolled_tree_header_box is not None
            assert abs(scrolled_tree_header_box["y"] - initial_top) <= 1.0
        finally:
            for path in seeded_dirs:
                path.rmdir()

    def test_library_right_pane_scrolls_with_mouse_wheel(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        review_root = Path("/tmp/pullbox-e2e-library")
        seeded_dirs = [review_root / f"zz-scroll-{index:03d}" for index in range(90)]
        for path in seeded_dirs:
            path.mkdir(exist_ok=True)
        try:
            library = LibraryPage(authed_page, seeded_server)
            library.goto()

            metrics = library.browser_table_wrap.evaluate(
                """(node) => ({
                  scrollHeight: node.scrollHeight,
                  clientHeight: node.clientHeight,
                  scrollTop: node.scrollTop,
                })"""
            )
            assert metrics["scrollHeight"] > metrics["clientHeight"]
            assert metrics["scrollTop"] == 0

            library.browser_table_wrap.hover()
            authed_page.mouse.wheel(0, 1200)
            authed_page.wait_for_timeout(150)

            after_scroll = library.browser_table_wrap.evaluate("(node) => node.scrollTop")
            assert after_scroll > 0
        finally:
            for path in seeded_dirs:
                path.rmdir()

    def test_library_browse_navigates_into_folder(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        library = LibraryPage(authed_page, seeded_server)
        library.goto()

        library.open_folder("01-batman")

        assert library.current_breadcrumb.is_visible()
        assert library.current_breadcrumb.inner_text().endswith("/01-batman")
        assert library.row_text("cover.png").is_visible()

    def test_library_context_menu_shows_folder_actions_and_properties_modal(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        library = LibraryPage(authed_page, seeded_server)
        library.goto()

        library.right_click_row("01-batman")

        assert library.context_action("properties").is_visible()
        assert library.context_action("rename").is_visible()
        assert library.context_action("auto-rename").is_visible()
        assert library.context_action("delete").is_visible()
        assert library.context_action("convert").count() == 0

        library.context_action("properties").click()

        library.properties_modal.wait_for(state="visible", timeout=5000)
        assert library.properties_modal.is_visible()
        assert library.properties_modal.get_by_text("01-batman", exact=True).first.is_visible()

    def test_library_context_menu_limits_root_to_properties_only(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        library = LibraryPage(authed_page, seeded_server)
        library.goto()

        library.right_click_tree_label("E2E Library")

        assert library.context_action("properties").is_visible()
        assert library.context_action("rename").count() == 0
        assert library.context_action("auto-rename").count() == 0
        assert library.context_action("convert").count() == 0
        assert library.context_action("delete").count() == 0

    def test_library_context_menu_hides_convert_for_non_convertible_files(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        library = LibraryPage(authed_page, seeded_server)
        library.goto_path("/tmp/pullbox-e2e-library/01-batman")

        library.right_click_row("cover.png")

        assert library.context_action("properties").is_visible()
        assert library.context_action("rename").is_visible()
        assert library.context_action("auto-rename").is_visible()
        assert library.context_action("delete").is_visible()
        assert library.context_action("convert").count() == 0

    def test_library_context_menu_shows_convert_for_convertible_files(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        sample_file = Path("/tmp/pullbox-e2e-library/01-batman/library-context-test.cbr")
        sample_file.write_bytes(b"rar-ish")
        try:
            library = LibraryPage(authed_page, seeded_server)
            library.goto_path("/tmp/pullbox-e2e-library/01-batman")

            library.right_click_row("library-context-test.cbr")

            assert library.context_action("convert").is_visible()
        finally:
            sample_file.unlink(missing_ok=True)

    def test_library_delete_action_opens_file_delete_modal(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        library = LibraryPage(authed_page, seeded_server)
        library.goto_path("/tmp/pullbox-e2e-library/01-batman")

        library.right_click_row("cover.png")
        library.context_action("delete").click()

        library.delete_file_modal.wait_for(state="visible", timeout=5000)
        assert library.delete_file_modal.is_visible()

    def test_library_folder_rename_modal_uses_structured_modal_contract(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        library = LibraryPage(authed_page, seeded_server)
        library.goto()

        library.right_click_row("01-batman")
        library.context_action("rename").click()

        library.rename_modal.wait_for(state="visible", timeout=5000)
        assert library.rename_modal.get_by_text("Rename Folder", exact=True).is_visible()
        assert (
            library.rename_modal.locator(
                "[data-testid='library-rename-summary-row'] .settings-row-label"
            ).count()
            == 0
        )
        assert (
            library.rename_modal.locator(
                "[data-testid='library-rename-summary-row'] .settings-row-help"
            ).count()
            == 0
        )
        assert (
            library.rename_modal.get_by_test_id("library-rename-name-header").inner_text().strip()
            == "New Name"
        )
        assert library.rename_modal.get_by_test_id("library-rename-name-panel").is_visible()
        assert (
            library.rename_modal.get_by_test_id("library-rename-path-header").inner_text().strip()
            == "Final Path"
        )
        assert library.rename_modal.get_by_test_id("library-rename-path-panel").is_visible()
        assert library.rename_action_note.is_visible()
        assert "immediately" in library.rename_action_note.inner_text().lower()
        assert library.rename_modal.get_by_text("Current Name", exact=True).count() == 0
        assert library.rename_modal.get_by_text("Preview Name", exact=True).count() == 0
        assert library.rename_modal.get_by_text("Queue Rename", exact=True).count() == 0
        assert library.rename_modal.locator("input").count() == 1
        authed_page.wait_for_function(
            """
            () =>
              document.activeElement ===
              document.querySelector("[data-testid='library-rename-input']")
            """
        )

        library.rename_input.fill("01-batman deluxe")

        assert library.rename_path_preview.inner_text().endswith("/01-batman deluxe")

    def test_library_file_rename_modal_uses_structured_modal_contract(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        library = LibraryPage(authed_page, seeded_server)
        library.goto_path("/tmp/pullbox-e2e-library/01-batman")

        library.right_click_row("cover.png")
        library.context_action("rename").click()

        library.rename_modal.wait_for(state="visible", timeout=5000)
        assert library.rename_modal.get_by_text("Rename File", exact=True).is_visible()
        assert (
            library.rename_modal.get_by_test_id("library-rename-name-header").inner_text().strip()
            == "New Name"
        )
        assert library.rename_modal.get_by_test_id("library-rename-name-panel").is_visible()
        assert (
            library.rename_modal.get_by_test_id("library-rename-path-header").inner_text().strip()
            == "Final Path"
        )
        assert library.rename_modal.get_by_test_id("library-rename-path-panel").is_visible()
        assert library.rename_input.input_value() == "cover"
        assert library.rename_path_preview.inner_text().endswith("/cover.png")
        assert (
            library.rename_modal.get_by_text(
                "Keep the existing file extension when renaming a library file.",
                exact=True,
            ).count()
            == 0
        )

        library.rename_input.fill("Batman cover")

        assert library.rename_path_preview.inner_text().endswith("/Batman cover.png")

    def test_library_file_rename_preserves_extension_on_submit(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        authed_page.route(
            "**/api/v1/library/browser/rename",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body="""
{"status":"ok","kind":"file","source_path":"/tmp/pullbox-e2e-library/01-batman/cover.png","target_path":"/tmp/pullbox-e2e-library/01-batman/Batman cover.png"}
""".strip(),
            ),
        )

        library = LibraryPage(authed_page, seeded_server)
        library.goto_path("/tmp/pullbox-e2e-library/01-batman")

        library.right_click_row("cover.png")
        library.context_action("rename").click()

        library.rename_modal.wait_for(state="visible", timeout=5000)
        library.rename_input.fill("Batman cover")

        with authed_page.expect_response(
            lambda response: (
                response.request.method == "POST"
                and "/api/v1/library/browser/rename" in response.url
            )
        ) as rename_response:
            library.rename_input.press("Enter")

        payload = rename_response.value.request.post_data_json or {}

        library.rename_modal.wait_for(state="hidden", timeout=5000)
        assert payload["path"].endswith("/pullbox-e2e-library/01-batman/cover.png")
        assert payload["proposed_name"] == "Batman cover.png"
        assert authed_page.get_by_text("Rename completed.", exact=True).is_visible()

    def test_library_folder_rename_submits_on_enter(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        authed_page.route(
            "**/api/v1/library/browser/rename",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body="""
{"status":"ok","kind":"folder","source_path":"/tmp/pullbox-e2e-library/01-batman","target_path":"/tmp/pullbox-e2e-library/01-batman deluxe"}
""".strip(),
            ),
        )

        library = LibraryPage(authed_page, seeded_server)
        library.goto()

        library.right_click_row("01-batman")
        library.context_action("rename").click()

        library.rename_modal.wait_for(state="visible", timeout=5000)
        library.rename_input.fill("01-batman deluxe")

        with authed_page.expect_response(
            lambda response: (
                response.request.method == "POST"
                and "/api/v1/library/browser/rename" in response.url
            )
        ) as rename_response:
            library.rename_input.press("Enter")

        payload = rename_response.value.request.post_data_json or {}

        library.rename_modal.wait_for(state="hidden", timeout=5000)
        assert payload["path"].endswith("/pullbox-e2e-library/01-batman")
        assert payload["proposed_name"] == "01-batman deluxe"
        assert authed_page.get_by_text("Rename completed.", exact=True).is_visible()

    def test_library_rename_blocked_modal_uses_structured_contract(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        authed_page.route(
            "**/api/v1/library/browser/entry*",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body="""
{
  "name":"01-batman",
  "path":"/tmp/pullbox-e2e-library/01-batman",
  "kind":"folder",
  "kind_label":"Folder",
  "root_name":"E2E Library",
  "root_path":"/tmp/pullbox-e2e-library",
  "file_format":null,
  "size_bytes":null,
  "item_count":3,
  "modified_at":null,
  "permissions_label":null,
  "actions":{
    "can_properties":true,
    "can_rename":true,
    "can_auto_rename":true,
    "can_convert":false,
    "can_delete":true
  },
  "delete_context":{
    "mode":"series",
    "trash_enabled":true,
    "series_id":1,
    "series_title":"Batman",
    "linked_file_count":2,
    "tracked_file_count":2,
    "tracked_series_count":1,
    "has_linked_issue":false,
    "issue_status_after_delete":null,
    "issue_status_reason":null
  },
  "rename_context":{
    "stale_reference":true,
    "reason_code":"stale_series_path",
    "message":"This folder is associated with a series in Pullbox, but the stored series path does not match the folder on disk. Run the Database Integrity Check before renaming it from Library.",
    "db_check_url":"/utilities/db-check"
  },
  "storage":{
    "total_bytes":null,
    "used_bytes":null,
    "free_bytes":null,
    "used_pct":null
  }
}
""".strip(),
            ),
        )

        library = LibraryPage(authed_page, seeded_server)
        library.goto()

        library.right_click_row("01-batman")
        library.context_action("rename").click()

        library.rename_stale_modal.wait_for(state="visible", timeout=5000)
        assert library.rename_stale_modal.is_visible()
        assert library.rename_stale_modal.get_by_test_id("library-rename-stale-reason").is_visible()
        assert (
            library.rename_stale_modal.locator(
                "[data-testid='library-rename-stale-warning-row'] .settings-row-label"
            ).count()
            == 0
        )
        assert (
            library.rename_stale_modal.locator(
                "[data-testid='library-rename-stale-warning-row'] .settings-row-help"
            ).count()
            == 0
        )
        assert (
            library.rename_stale_modal.get_by_test_id("library-rename-stale-repair-header")
            .inner_text()
            .strip()
            == "Repair Path"
        )
        assert library.rename_stale_modal.get_by_test_id(
            "library-rename-stale-repair-grid"
        ).is_visible()
        assert (
            library.rename_stale_modal.locator(
                "[data-testid='library-rename-stale-repair-grid'] tbody tr"
            ).count()
            == 2
        )
        repair_spacing = library.rename_stale_modal.evaluate("""
            modal => {
              const repair = modal.querySelector("[data-testid='library-rename-stale-next-step']");
              const footer = modal.querySelector(".modal-footer");
              if (!repair || !footer) return -1;
              return Math.round(footer.getBoundingClientRect().top - repair.getBoundingClientRect().bottom);
            }
        """)
        assert repair_spacing >= 12
        assert library.rename_stale_modal.get_by_test_id("library-rename-stale-note").count() == 0
        assert library.rename_stale_modal.locator(".library-browser-modal__helper").count() == 0

    def test_library_auto_rename_submits_immediately_from_preview(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        authed_page.route(
            "**/api/v1/utilities/rename/preview",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body="""
{
  "target":"folders",
  "scope":"manual",
  "item_count":1,
  "actionable_count":1,
  "items":[
    {
      "file_path":"/tmp/pullbox-e2e-library/01-batman",
      "current_name":"01-batman",
      "proposed_name":"Batman (2016)",
      "template_key":"folder_template",
      "template_label":"Series folder",
      "actionable":true,
      "status":"ready",
      "reason":null
    }
  ]
}
""".strip(),
            ),
        )
        authed_page.route(
            "**/api/v1/library/browser/rename",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body="""
{"status":"ok","kind":"folder","source_path":"/tmp/pullbox-e2e-library/01-batman","target_path":"/tmp/pullbox-e2e-library/Batman (2016)"}
""".strip(),
            ),
        )

        library = LibraryPage(authed_page, seeded_server)
        library.goto()

        library.right_click_row("01-batman")
        library.context_action("auto-rename").click()

        library.auto_rename_modal.wait_for(state="visible", timeout=5000)
        assert library.auto_rename_modal.get_by_text(
            "Rename Automatically", exact=True
        ).is_visible()
        assert library.auto_rename_action_note.is_visible()
        assert "immediately" in library.auto_rename_action_note.inner_text().lower()
        assert (
            library.auto_rename_modal.locator(
                "[data-testid='library-auto-rename-summary-row'] .settings-row-label"
            ).count()
            == 0
        )
        assert (
            library.auto_rename_modal.locator(
                "[data-testid='library-auto-rename-summary-row'] .settings-row-help"
            ).count()
            == 0
        )
        assert (
            library.auto_rename_modal.get_by_test_id("library-auto-rename-preview-header")
            .inner_text()
            .strip()
            == "Preview"
        )
        assert library.auto_rename_modal.get_by_test_id(
            "library-auto-rename-preview-grid"
        ).is_visible()
        expect(
            library.auto_rename_modal.locator(
                "[data-testid='library-auto-rename-preview-grid'] tbody tr"
            )
        ).to_have_count(4)
        assert library.auto_rename_modal.get_by_text("Queue Rename", exact=True).count() == 0

        with authed_page.expect_response(
            lambda response: (
                response.request.method == "POST"
                and "/api/v1/library/browser/rename" in response.url
            )
        ) as rename_response:
            library.auto_rename_modal.get_by_test_id("library-auto-rename-submit").click()

        payload = rename_response.value.request.post_data_json or {}

        library.auto_rename_modal.wait_for(state="hidden", timeout=5000)
        assert payload["path"].endswith("/pullbox-e2e-library/01-batman")
        assert payload["proposed_name"] == "Batman (2016)"
        assert authed_page.get_by_text("Rename completed.", exact=True).is_visible()

    def test_library_file_auto_rename_modal_uses_structured_modal_contract(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        authed_page.route(
            "**/api/v1/utilities/rename/preview",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body="""
{
  "target":"files",
  "scope":"manual",
  "item_count":1,
  "actionable_count":1,
  "items":[
    {
      "file_path":"/tmp/pullbox-e2e-library/01-batman/cover.png",
      "current_name":"cover.png",
      "proposed_name":"Batman (2016) cover.png",
      "template_key":"issue_file_template",
      "template_label":"Issue File",
      "actionable":true,
      "status":"ready",
      "reason":null
    }
  ]
}
""".strip(),
            ),
        )
        authed_page.route(
            "**/api/v1/library/browser/rename",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body="""
{"status":"ok","kind":"file","source_path":"/tmp/pullbox-e2e-library/01-batman/cover.png","target_path":"/tmp/pullbox-e2e-library/01-batman/Batman (2016) cover.png"}
""".strip(),
            ),
        )

        library = LibraryPage(authed_page, seeded_server)
        library.goto_path("/tmp/pullbox-e2e-library/01-batman")

        library.right_click_row("cover.png")
        library.context_action("auto-rename").click()

        library.auto_rename_modal.wait_for(state="visible", timeout=5000)
        assert library.auto_rename_action_note.is_visible()
        assert (
            library.auto_rename_modal.get_by_test_id("library-auto-rename-preview-header")
            .inner_text()
            .strip()
            == "Preview"
        )
        expect(
            library.auto_rename_modal.locator(
                "[data-testid='library-auto-rename-preview-grid'] tbody tr"
            )
        ).to_have_count(4)

    def test_library_delete_action_opens_series_delete_modal_for_tracked_series_folder(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        library = LibraryPage(authed_page, seeded_server)
        library.goto()

        library.right_click_row("01-batman")
        library.context_action("delete").click()

        library.delete_series_modal.wait_for(state="visible", timeout=5000)
        assert library.delete_series_modal.is_visible()
        assert library.delete_series_modal.get_by_text("Delete Folder and Series").is_visible()
        assert library.delete_series_modal.get_by_test_id(
            "library-delete-series-warning-row"
        ).is_visible()
        assert library.delete_series_modal.get_by_test_id(
            "library-delete-series-summary"
        ).is_visible()
        assert (
            library.delete_series_modal.locator(
                "[data-testid='library-delete-series-warning-row'] .settings-row-label"
            ).count()
            == 0
        )
        assert (
            library.delete_series_modal.locator(
                "[data-testid='library-delete-series-warning-row'] .settings-row-help"
            ).count()
            == 0
        )
        assert (
            library.delete_series_modal.get_by_test_id("library-delete-series-impact-header")
        ).is_visible()
        assert (
            library.delete_series_modal.get_by_test_id("library-delete-series-impact-header")
            .inner_text()
            .strip()
            == "Impact"
        )
        assert (
            library.delete_series_modal.get_by_test_id("library-delete-series-impact-grid")
        ).is_visible()
        assert (
            library.delete_series_modal.locator(
                "[data-testid='library-delete-series-impact-grid'] tbody tr"
            ).count()
            == 4
        )
        assert (
            library.delete_series_modal.locator("[data-testid='series-delete-files']").count() == 0
        )
        assert (
            library.delete_series_modal.locator("[data-testid='series-delete-folders']").count()
            == 0
        )

    def test_library_delete_action_opens_folder_delete_modal(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        library = LibraryPage(authed_page, seeded_server)
        library.goto()

        library.right_click_tree_label("99-misc-folder")
        library.context_action("delete").click()

        library.delete_folder_modal.wait_for(state="visible", timeout=5000)
        assert library.delete_folder_modal.is_visible()
        assert library.delete_folder_modal.get_by_test_id(
            "library-delete-folder-warning-row"
        ).is_visible()
        assert library.delete_folder_modal.get_by_test_id(
            "library-delete-folder-summary"
        ).is_visible()
        assert (
            library.delete_folder_modal.locator(
                "[data-testid='library-delete-folder-warning-row'] .settings-row-label"
            ).count()
            == 0
        )
        assert (
            library.delete_folder_modal.locator(
                "[data-testid='library-delete-folder-warning-row'] .settings-row-help"
            ).count()
            == 0
        )
        assert (
            library.delete_folder_modal.get_by_test_id("library-delete-folder-impact-header")
        ).is_visible()
        assert (
            library.delete_folder_modal.get_by_test_id("library-delete-folder-impact-header")
            .inner_text()
            .strip()
            == "Impact"
        )
        assert (
            library.delete_folder_modal.get_by_test_id("library-delete-folder-impact-grid")
        ).is_visible()
        assert (
            library.delete_folder_modal.locator(
                "[data-testid='library-delete-folder-impact-grid'] tbody tr"
            ).count()
            == 4
        )

    def test_library_delete_action_opens_structured_file_delete_modal(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        library = LibraryPage(authed_page, seeded_server)
        library.goto_path("/tmp/pullbox-e2e-library/01-batman")

        library.right_click_row("cover.png")
        library.context_action("delete").click()

        library.delete_file_modal.wait_for(state="visible", timeout=5000)
        assert library.delete_file_modal.get_by_test_id(
            "library-delete-file-warning-row"
        ).is_visible()
        assert library.delete_file_modal.get_by_test_id("library-delete-file-summary").is_visible()
        assert (
            library.delete_file_modal.locator(
                "[data-testid='library-delete-file-warning-row'] .settings-row-label"
            ).count()
            == 0
        )
        assert (
            library.delete_file_modal.locator(
                "[data-testid='library-delete-file-warning-row'] .settings-row-help"
            ).count()
            == 0
        )
        assert (
            library.delete_file_modal.get_by_test_id("library-delete-file-impact-header")
        ).is_visible()
        assert (
            library.delete_file_modal.get_by_test_id("library-delete-file-impact-header")
            .inner_text()
            .strip()
            == "Impact"
        )
        assert (
            library.delete_file_modal.get_by_test_id("library-delete-file-impact-grid")
        ).is_visible()
        assert (
            library.delete_file_modal.locator(
                "[data-testid='library-delete-file-impact-grid'] tbody tr"
            ).count()
            == 4
        )

    def test_library_convert_modal_uses_structured_preview_contract(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        sample_file = Path("/tmp/pullbox-e2e-library/01-batman/library-context-test.cbr")
        sample_file.write_bytes(b"rar-ish")
        authed_page.route(
            "**/api/v1/utilities/mass-convert/preview",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body="""
{
  "scope":"manual",
  "item_count":1,
  "total_size_bytes":7,
  "items":[
    {
      "file_path":"/tmp/pullbox-e2e-library/01-batman/library-context-test.cbr",
      "source_name":"library-context-test.cbr",
      "source_format":"CBR",
      "output_name":"library-context-test.cbz",
      "size_bytes":7
    }
  ]
}
""".strip(),
            ),
        )

        try:
            library = LibraryPage(authed_page, seeded_server)
            library.goto_path("/tmp/pullbox-e2e-library/01-batman")

            library.right_click_row("library-context-test.cbr")
            library.context_action("convert").click()

            library.convert_modal.wait_for(state="visible", timeout=5000)
            assert library.convert_modal.get_by_test_id("library-convert-summary-row").is_visible()
            assert library.convert_action_note.is_visible()
            assert "converts this file now" in library.convert_action_note.inner_text().lower()
            assert (
                library.convert_modal.locator(
                    "[data-testid='library-convert-modal'] .settings-row"
                ).count()
                == 0
            )
            assert library.convert_modal.get_by_test_id(
                "library-convert-preview-header"
            ).is_visible()
            expect(
                library.convert_modal.locator(
                    "[data-testid='library-convert-preview-grid'] tbody tr"
                )
            ).to_have_count(3)
        finally:
            sample_file.unlink(missing_ok=True)

    def test_library_convert_submits_immediately(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        sample_file = Path("/tmp/pullbox-e2e-library/01-batman/library-context-test.cbr")
        sample_file.write_bytes(b"rar-ish")
        authed_page.route(
            "**/api/v1/utilities/mass-convert/preview",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body="""
{
  "scope":"manual",
  "item_count":1,
  "total_size_bytes":7,
  "items":[
    {
      "file_path":"/tmp/pullbox-e2e-library/01-batman/library-context-test.cbr",
      "source_name":"library-context-test.cbr",
      "source_format":"CBR",
      "output_name":"library-context-test.cbz",
      "size_bytes":7
    }
  ]
}
""".strip(),
            ),
        )
        authed_page.route(
            "**/api/v1/library/browser/convert",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body="""
{"status":"ok","kind":"file","source_path":"/tmp/pullbox-e2e-library/01-batman/library-context-test.cbr","target_path":"/tmp/pullbox-e2e-library/01-batman/library-context-test.cbz","original_trash_path":"/tmp/pullbox-e2e-library/.trash/01-batman/library-context-test.cbr"}
""".strip(),
            ),
        )

        try:
            library = LibraryPage(authed_page, seeded_server)
            library.goto_path("/tmp/pullbox-e2e-library/01-batman")

            library.right_click_row("library-context-test.cbr")
            library.context_action("convert").click()

            library.convert_modal.wait_for(state="visible", timeout=5000)
            with authed_page.expect_response(
                lambda response: (
                    response.request.method == "POST"
                    and "/api/v1/library/browser/convert" in response.url
                )
            ) as convert_response:
                library.convert_modal.get_by_test_id("library-convert-submit").click()

            payload = convert_response.value.request.post_data_json or {}

            library.convert_modal.wait_for(state="hidden", timeout=5000)
            assert payload["path"].endswith(
                "/pullbox-e2e-library/01-batman/library-context-test.cbr"
            )
            assert authed_page.get_by_text("Conversion completed.", exact=True).is_visible()
        finally:
            sample_file.unlink(missing_ok=True)
