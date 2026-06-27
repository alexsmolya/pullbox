"""Focused browser coverage for the rewritten system shell."""

from __future__ import annotations

import json

import pytest

from tests.e2e.pages.system import SystemPage

pytestmark = pytest.mark.e2e


class TestSystemPage:
    """Behavior-first E2E checks for the system shell."""

    def test_system_renders_stable_shell(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        system = SystemPage(authed_page, seeded_server)
        system.goto()

        assert system.page_root.is_visible()
        assert system.header.is_visible()
        assert system.body.is_visible()
        assert system.tabs.is_visible()
        assert system.content.is_visible()
        assert system.panel("about").is_visible()
        assert system.tab("about").get_attribute("aria-current") == "page"

    def test_system_tab_switch_keeps_shell_stable(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        system = SystemPage(authed_page, seeded_server)
        system.goto()

        system.switch_tab("tasks")

        assert system.page_root.is_visible()
        assert authed_page.locator("[data-testid='system-page']").count() == 1
        assert authed_page.locator("[data-testid='system-body']").count() == 1
        assert authed_page.locator("[data-testid='system-tabs']").count() == 1
        assert authed_page.locator("[data-testid='system-content']").count() == 1
        assert system.panel("tasks").is_visible()
        assert system.tab("tasks").get_attribute("aria-current") == "page"

    def test_system_tab_switch_preserves_left_nav_node(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        system = SystemPage(authed_page, seeded_server)
        system.goto()

        authed_page.evaluate(
            """
            () => {
              const nav = document.getElementById("system-tabs");
              if (nav) {
                nav.dataset.preserved = "yes";
              }
            }
            """
        )

        system.switch_tab("tasks")

        assert (
            authed_page.locator("[data-testid='system-tabs']").evaluate(
                "(node) => node.dataset.preserved || ''"
            )
            == "yes"
        )
        assert system.tab("tasks").get_attribute("aria-current") == "page"

    def test_system_direct_tab_load_renders_matching_panel(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        system = SystemPage(authed_page, seeded_server)
        system.goto("logs")

        assert system.page_root.is_visible()
        assert system.panel("logs").is_visible()
        assert system.tab("logs").get_attribute("aria-current") == "page"

    def test_system_tasks_does_not_refetch_registry_on_initial_tab_load(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        request_count = 0

        def track_tasks(route) -> None:  # type: ignore[no-untyped-def]
            nonlocal request_count
            request_count += 1
            route.continue_()

        authed_page.route("**/api/v1/system/tasks", track_tasks)

        system = SystemPage(authed_page, seeded_server)
        system.goto("tasks")
        system.panel("tasks").wait_for(state="visible", timeout=5000)
        authed_page.evaluate(
            "() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))"
        )

        assert request_count == 0

    def test_system_logs_does_not_refetch_registry_on_initial_tab_load(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        request_count = 0

        def track_logs(route) -> None:  # type: ignore[no-untyped-def]
            nonlocal request_count
            request_count += 1
            route.continue_()

        authed_page.route("**/api/v1/system/logs", track_logs)

        system = SystemPage(authed_page, seeded_server)
        system.goto("logs")
        system.panel("logs").wait_for(state="visible", timeout=5000)
        authed_page.evaluate(
            "() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))"
        )

        assert request_count == 0

    def test_system_first_cards_align_to_same_top_rail(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        system = SystemPage(authed_page, seeded_server)
        system.goto()

        about_card = authed_page.locator("[data-testid='system-about-version-banner']").first
        about_box = about_card.bounding_box()
        assert about_box is not None

        card_map = {
            "tasks": "[data-testid='system-panel-tasks'] .section-card",
            "logs": "[data-testid='system-panel-logs'] .section-card",
            "backup": "[data-testid='system-panel-backup'] .section-card",
            "support": "[data-testid='system-panel-support'] .section-card",
        }

        for tab, selector in card_map.items():
            system.switch_tab(tab)
            target = authed_page.locator(selector).first
            target_box = target.bounding_box()

            assert target_box is not None
            assert abs(target_box["y"] - about_box["y"]) <= 2, (
                f"{tab} top card y={target_box['y']} does not match about y={about_box['y']}"
            )

    def test_system_page_emits_no_about_info_null_errors(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        errors: list[str] = []
        console_messages: list[str] = []
        authed_page.on("pageerror", lambda exc: errors.append(str(exc)))
        authed_page.on(
            "console",
            lambda msg: (
                console_messages.append(msg.text) if msg.type in {"warning", "error"} else None
            ),
        )

        system = SystemPage(authed_page, seeded_server)
        system.goto()

        system.switch_tab("backup")
        system.switch_tab("tasks")
        system.switch_tab("logs")
        system.switch_tab("support")
        system.switch_tab("about")

        assert system.page_root.is_visible()
        assert not errors
        assert not any("Cannot read properties of null" in message for message in console_messages)

    def test_system_support_dropdown_keeps_shell_stable(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        system = SystemPage(authed_page, seeded_server)
        system.goto("support")

        system.select_dropdown_option("system-support-debug-duration-select", "120")

        assert system.page_root.is_visible()
        assert system.panel("support").is_visible()
        assert system.dropdown_value("system-support-debug-duration-select") == "120"
        assert system.dropdown_label("system-support-debug-duration-select") == "2 hours"

    def test_system_tasks_refresh_renders_human_interval_and_run_state(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        authed_page.route(
            "**/api/v1/system/tasks",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "scheduled": [
                            {
                                "task_id": "backfill_series_covers",
                                "name": "Backfill Series Covers",
                                "interval": "interval[1 day, 0:00:00]",
                                "next_run_time": "2026-04-21T12:00:00+00:00",
                                "last_execution": "2026-04-20T11:58:00+00:00",
                                "last_duration_seconds": 3.21,
                                "last_status": "completed",
                            }
                        ]
                    }
                ),
            ),
        )

        system = SystemPage(authed_page, seeded_server)
        system.goto("tasks")

        authed_page.get_by_role("button", name="Refresh", exact=True).click()
        authed_page.wait_for_function(
            """
            () => {
              const cell = document.querySelector("[data-testid='system-tasks-table'] tbody tr td:nth-child(1)");
              return !!cell && cell.textContent && cell.textContent.includes("Backfill Series Covers");
            }
            """,
            timeout=5000,
        )
        row = authed_page.locator("[data-testid='system-tasks-table'] tbody tr").first
        row.wait_for(state="visible", timeout=5000)

        cells = row.locator("td")
        assert "Backfill Series Covers" in cells.nth(0).inner_text()
        assert cells.nth(1).inner_text() == "1 day"
        assert "Never" not in cells.nth(2).inner_text()
        assert cells.nth(3).inner_text() == "3.21 sec"
        assert cells.nth(5).inner_text() == "Healthy"

    def test_system_tasks_auto_refresh_note_sits_below_refresh_button(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        authed_page.set_viewport_size({"width": 1400, "height": 1000})
        system = SystemPage(authed_page, seeded_server)
        system.goto("tasks")

        geometry = authed_page.evaluate(
            """
            () => {
              const button = document.querySelector("[data-testid='system-panel-tasks'] button.btn-primary");
              const note = document.querySelector("[data-testid='system-tasks-auto-refresh-note']");
              if (!button || !note) return null;
              const buttonRect = button.getBoundingClientRect();
              const noteRect = note.getBoundingClientRect();
              return {
                buttonBottom: buttonRect.bottom,
                noteTop: noteRect.top,
                noteRight: noteRect.right,
                buttonRight: buttonRect.right
              };
            }
            """,
        )

        assert geometry is not None
        assert geometry["noteTop"] > geometry["buttonBottom"] - 1
        assert abs(geometry["noteRight"] - geometry["buttonRight"]) < 12

    def test_system_tasks_renders_duration_units(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        authed_page.route(
            "**/api/v1/system/tasks",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "scheduled": [
                            {
                                "task_id": "run_backups",
                                "name": "Backup",
                                "interval": "cron[hour='3', minute='0']",
                                "next_run_time": "2026-04-22T10:00:00+00:00",
                                "last_execution": "2026-04-21T05:21:16+00:00",
                                "last_duration_seconds": 0.21,
                                "last_status": "completed",
                            },
                            {
                                "task_id": "monitor_downloads",
                                "name": "Monitor Downloads",
                                "interval": "interval[0:00:03]",
                                "next_run_time": "2026-04-21T05:22:00+00:00",
                                "last_execution": "2026-04-21T05:21:59+00:00",
                                "last_duration_seconds": 0.0,
                                "last_status": "completed",
                            },
                            {
                                "task_id": "sync_recent_issues",
                                "name": "Sync Recent Issues",
                                "interval": "interval[1 day, 0:00:00]",
                                "next_run_time": "2026-04-22T05:22:00+00:00",
                                "last_execution": "2026-04-21T05:10:59+00:00",
                                "last_duration_seconds": 65.0,
                                "last_status": "completed",
                            },
                            {
                                "task_id": "sync_issue_catalog",
                                "name": "Sync Issue Catalog",
                                "interval": "interval[14 days, 0:00:00]",
                                "next_run_time": "2026-05-05T05:22:00+00:00",
                                "last_execution": "2026-04-21T03:18:36+00:00",
                                "last_duration_seconds": 7324.0,
                                "last_status": "completed",
                            },
                        ]
                    }
                ),
            ),
        )

        system = SystemPage(authed_page, seeded_server)
        system.goto("tasks")

        authed_page.get_by_role("button", name="Refresh", exact=True).click()
        rows = authed_page.locator("[data-testid='system-tasks-table'] tbody tr")
        rows.nth(0).wait_for(state="visible", timeout=5000)
        authed_page.wait_for_function(
            """
            () => {
              const cell = document.querySelector("[data-testid='system-tasks-table'] tbody tr td:nth-child(4)");
              return !!cell && cell.textContent && cell.textContent.includes("0.21 sec");
            }
            """,
            timeout=5000,
        )

        first = rows.nth(0).locator("td")
        second = rows.nth(1).locator("td")
        third = rows.nth(2).locator("td")
        fourth = rows.nth(3).locator("td")

        assert first.nth(3).inner_text() == "0.21 sec"
        assert second.nth(3).inner_text() == "< 0.01 sec"
        assert third.nth(3).inner_text() == "1 min 05 sec"
        assert fourth.nth(3).inner_text() == "2 hrs 02 min 04 sec"

    def test_system_tasks_running_state_replaces_never_run(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        authed_page.route(
            "**/api/v1/system/tasks",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "scheduled": [
                            {
                                "task_id": "search_wanted",
                                "name": "Search Wanted",
                                "interval": "interval[6:00:00]",
                                "next_run_time": "2026-04-21T12:00:00+00:00",
                                "last_execution": None,
                                "last_duration_seconds": None,
                                "last_status": None,
                                "is_running": True,
                            }
                        ]
                    }
                ),
            ),
        )

        system = SystemPage(authed_page, seeded_server)
        system.goto("tasks")

        authed_page.get_by_role("button", name="Refresh", exact=True).click()
        authed_page.wait_for_function(
            """
            () => {
              const cell = document.querySelector("[data-testid='system-tasks-table'] tbody tr td:nth-child(3)");
              return !!cell && cell.textContent && cell.textContent.includes("Running now");
            }
            """,
            timeout=5000,
        )
        row = authed_page.locator("[data-testid='system-tasks-table'] tbody tr").first
        row.wait_for(state="visible", timeout=5000)

        cells = row.locator("td")
        assert "Running now" in cells.nth(2).inner_text()
        assert "In progress" in cells.nth(3).inner_text()
        assert cells.nth(5).inner_text() == "Running"

    def test_system_tasks_queued_state_surfaces_manual_queue_position(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        authed_page.route(
            "**/api/v1/system/tasks",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "scheduled": [
                            {
                                "task_id": "refresh_metadata",
                                "name": "Refresh Metadata",
                                "interval": "cron[hour='3', minute='15']",
                                "next_run_time": "2026-04-21T12:00:00+00:00",
                                "last_execution": "2026-04-21T05:21:16+00:00",
                                "last_duration_seconds": 0.21,
                                "last_status": "completed",
                                "is_queued": True,
                                "manual_queue_position": 1,
                            }
                        ]
                    }
                ),
            ),
        )

        system = SystemPage(authed_page, seeded_server)
        system.goto("tasks")

        authed_page.get_by_role("button", name="Refresh", exact=True).click()
        row = authed_page.locator("[data-testid='system-tasks-table'] tbody tr").first
        row.wait_for(state="visible", timeout=5000)
        authed_page.wait_for_function(
            """
            () => {
              const cell = document.querySelector("[data-testid='system-tasks-table'] tbody tr td:nth-child(3)");
              return !!cell && cell.textContent && cell.textContent.includes("Queued (#1)");
            }
            """,
            timeout=5000,
        )

        cells = row.locator("td")
        assert "Queued (#1)" in cells.nth(2).inner_text()
        assert "Pending queue" in cells.nth(3).inner_text()
        assert cells.nth(5).inner_text() == "Queued"

    def test_system_logs_shared_viewer_contract_behaves_consistently(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        errors: list[str] = []
        console_messages: list[str] = []
        authed_page.on("pageerror", lambda exc: errors.append(str(exc)))
        authed_page.on(
            "console",
            lambda msg: (
                console_messages.append(msg.text) if msg.type in {"warning", "error"} else None
            ),
        )

        authed_page.route(
            "**/api/v1/system/logs",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    [
                        {
                            "filename": "app.log",
                            "modified_at": "2026-04-05T08:00:00Z",
                            "size_bytes": 2048,
                        }
                    ]
                ),
            ),
        )
        authed_page.route(
            "**/api/v1/system/logs/app.log/content**",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "lines": [
                            json.dumps(
                                {
                                    "timestamp": "2026-04-05T08:12:34Z",
                                    "level": "warning",
                                    "event": "tail-test",
                                    "detail": "viewer contract",
                                    "file_path": (
                                        "/Users/adam/Downloads/extremely/long/path/that/should/"
                                        "stay/inside/the/system/log/viewer/container/when/the/"
                                        "entry/is/expanded/app.log"
                                    ),
                                }
                            )
                        ],
                        "total_lines": 1,
                        "truncated": False,
                    }
                ),
            ),
        )

        system = SystemPage(authed_page, seeded_server)
        system.goto("logs")

        authed_page.get_by_role("button", name="Refresh").click()
        authed_page.get_by_text("app.log", exact=True).click()
        viewer = authed_page.locator("[data-testid='system-log-viewer']").first
        viewer.wait_for(state="visible", timeout=5000)

        assert viewer.locator("[data-testid='system-log-search-field']").is_visible()
        assert viewer.locator("[data-testid='system-log-lines-select']").is_visible()
        assert viewer.locator("[data-testid='system-log-download']").is_visible()
        assert viewer.locator("[data-testid='system-log-refresh']").is_visible()
        assert viewer.locator("[data-testid='system-log-close']").is_visible()
        assert viewer.locator("[data-testid='system-log-live-toggle']").is_visible()
        assert (
            viewer.locator("[data-testid='system-log-download']").get_attribute("data-tip")
            == "Download"
        )
        assert (
            viewer.locator("[data-testid='system-log-refresh']").get_attribute("data-tip")
            == "Refresh"
        )
        assert (
            viewer.locator("[data-testid='system-log-close']").get_attribute("data-tip") == "Close"
        )
        assert viewer.locator("[data-testid='system-log-auto-scroll']").count() == 0
        assert (
            viewer.locator("[data-testid='system-log-download']").get_attribute("href")
            == "/api/v1/system/logs/app.log/download"
        )
        body = viewer.locator("[data-testid='system-log-viewer-body']").first
        assert body.locator(".log-line").first.is_visible()
        assert body.get_by_text(
            "tail-test · detail=viewer contract", exact=False
        ).first.is_visible()

        chevron = body.locator(".log-line-chevron").first
        chevron_styles = chevron.evaluate(
            """(node) => {
                const styles = window.getComputedStyle(node);
                return {
                    display: styles.display,
                    width: styles.width,
                    height: styles.height,
                    alignSelf: styles.alignSelf,
                };
            }"""
        )
        assert chevron_styles == {
            "display": "flex",
            "width": "28px",
            "height": "28px",
            "alignSelf": "center",
        }

        body.locator(".log-line").first.click()
        body.locator(".log-detail").first.wait_for(state="visible", timeout=5000)

        logs_panel = authed_page.locator("[data-testid='system-panel-logs']").first
        panel_box = logs_panel.bounding_box()
        viewer_box = viewer.bounding_box()
        assert panel_box is not None
        assert viewer_box is not None
        assert viewer_box["width"] <= panel_box["width"] + 2
        assert viewer.locator("[data-testid='system-log-download']").is_visible()
        assert viewer.locator("[data-testid='system-log-refresh']").is_visible()
        assert viewer.locator("[data-testid='system-log-close']").is_visible()
        assert not errors
        assert not any("this.timeAgo is not a function" in message for message in console_messages)
        assert not any("Alpine Expression Error" in message for message in console_messages)

        viewer.locator("[data-testid='system-log-close']").click()
        viewer.wait_for(state="hidden", timeout=5000)

    def test_system_logs_open_and_close_reposition_content_for_viewer(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        authed_page.route(
            "**/api/v1/system/logs",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    [
                        {
                            "filename": "app.log",
                            "modified_at": "2026-04-05T08:00:00Z",
                            "size_bytes": 2048,
                        }
                    ]
                ),
            ),
        )
        authed_page.route(
            "**/api/v1/system/logs/app.log/content**",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "lines": [
                            json.dumps(
                                {
                                    "timestamp": "2026-04-05T08:12:34Z",
                                    "level": "warning",
                                    "event": "tail-test",
                                    "detail": "viewer contract",
                                }
                            )
                        ],
                        "total_lines": 1,
                        "truncated": False,
                    }
                ),
            ),
        )

        system = SystemPage(authed_page, seeded_server)
        system.goto("logs")

        authed_page.get_by_role("button", name="Refresh").click()
        scroll_state = authed_page.evaluate(
            """
            () => {
              const content = document.getElementById("content");
              const table = document.querySelector("[data-testid='system-logs-table']");
              if (!content || !table) {
                return null;
              }

              const spacer = document.createElement("div");
              spacer.setAttribute("data-testid", "system-log-scroll-spacer");
              spacer.style.height = "1800px";
              table.insertAdjacentElement("afterend", spacer);
              content.scrollTop = 0;
              content.dispatchEvent(new Event("scroll"));

              return {
                beforeOpen: content.scrollTop,
              };
            }
            """
        )

        assert scroll_state is not None
        assert scroll_state["beforeOpen"] == 0

        authed_page.get_by_text("app.log", exact=True).click()
        viewer = authed_page.locator("[data-testid='system-log-viewer']").first
        viewer.wait_for(state="visible", timeout=5000)
        authed_page.wait_for_function(
            """
            () => {
              const content = document.getElementById("content");
              const viewer = document.querySelector("[data-testid='system-log-viewer']");
              return Boolean(content && viewer && content.scrollTop > 0);
            }
            """,
            timeout=5000,
        )

        opened_state = authed_page.evaluate(
            """
            () => {
              const content = document.getElementById("content");
              const viewer = document.querySelector("[data-testid='system-log-viewer']");
              if (!content || !viewer) {
                return null;
              }

              const contentRect = content.getBoundingClientRect();
              const viewerRect = viewer.getBoundingClientRect();

              return {
                scrollTop: content.scrollTop,
                viewerTop: viewerRect.top,
                contentTop: contentRect.top,
                contentBottom: contentRect.bottom,
              };
            }
            """
        )

        assert opened_state is not None
        assert opened_state["scrollTop"] > 0
        assert opened_state["viewerTop"] >= opened_state["contentTop"] - 2
        assert opened_state["viewerTop"] < opened_state["contentBottom"]

        viewer.locator("[data-testid='system-log-close']").click()
        viewer.wait_for(state="hidden", timeout=5000)
        authed_page.wait_for_function(
            """
            (previousScrollTop) => {
              const content = document.getElementById("content");
              return Boolean(content && content.scrollTop < previousScrollTop);
            }
            """,
            arg=opened_state["scrollTop"],
            timeout=5000,
        )

        closed_state = authed_page.evaluate(
            """
            () => {
              const content = document.getElementById("content");
              const root = document.querySelector("[data-testid='system-panel-logs'] [x-data]");
              if (!content || !root) {
                return null;
              }

              const contentRect = content.getBoundingClientRect();
              const rootRect = root.getBoundingClientRect();
              return {
                scrollTop: content.scrollTop,
                rootTop: rootRect.top,
                contentTop: contentRect.top,
              };
            }
            """
        )

        assert closed_state is not None
        assert closed_state["scrollTop"] < opened_state["scrollTop"]
        assert closed_state["rootTop"] >= closed_state["contentTop"] - 2
