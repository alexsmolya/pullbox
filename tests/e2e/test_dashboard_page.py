"""Focused browser coverage for the mission-control dashboard."""

from __future__ import annotations

import pytest

from tests.e2e.conftest import run_htmx_ajax_and_wait
from tests.e2e.pages.dashboard import DashboardPage

pytestmark = pytest.mark.e2e


class TestDashboardPage:
    """Behavior-first E2E checks for the dashboard shell."""

    def test_dashboard_renders_mission_control_regions(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        dashboard = DashboardPage(authed_page, seeded_server)
        dashboard.goto()

        assert dashboard.page_root.is_visible()
        assert dashboard.mission_control.is_visible()
        assert dashboard.gauge("completion").is_visible()
        assert dashboard.gauge("wanted").is_visible()
        assert dashboard.gauge("downloads").is_visible()
        assert dashboard.gauge("health").is_visible()
        assert dashboard.scoreboard.is_visible()
        assert dashboard.alerts.is_visible()
        assert dashboard.first_alert_sys_led.is_visible()
        sys_led_styles = dashboard.first_alert_sys_led.evaluate(
            """el => {
                const s = window.getComputedStyle(el);
                return {
                    backgroundColor: s.backgroundColor,
                    boxShadow: s.boxShadow,
                };
            }"""
        )
        assert sys_led_styles["backgroundColor"] != "rgba(0, 0, 0, 0)"
        assert sys_led_styles["boxShadow"] != "none"
        assert dashboard.download_exceptions_panel.is_visible()
        assert dashboard.first_download_exception_sys_led.is_visible()
        assert dashboard.recent_activity.is_visible()
        assert dashboard.footer_dock.is_visible()
        assert authed_page.get_by_text("Updated just now").count() == 0

    def test_dashboard_briefing_refresh_keeps_shell_stable(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        dashboard = DashboardPage(authed_page, seeded_server)
        dashboard.goto()

        run_htmx_ajax_and_wait(
            authed_page,
            "/htmx/dashboard/briefing",
            "#dashboard-mission-control-region",
        )

        assert dashboard.page_root.is_visible()
        assert dashboard.mission_control.is_visible()
        assert dashboard.scoreboard.is_visible()
        assert dashboard.alerts.is_visible()

    def test_dashboard_download_exceptions_refresh_keeps_shell_stable_after_sidebar_toggle(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        dashboard = DashboardPage(authed_page, seeded_server)
        dashboard.goto()

        authed_page.locator("[data-testid='sidebar-collapse-toggle']").click()
        authed_page.wait_for_function(
            """() => {
                const button = document.querySelector("[data-testid='sidebar-collapse-toggle']");
                return button && button.getAttribute("data-tip") === "Expand sidebar";
            }""",
            timeout=5000,
        )
        authed_page.locator("[data-testid='sidebar-collapse-toggle']").click()
        authed_page.wait_for_function(
            """() => {
                const button = document.querySelector("[data-testid='sidebar-collapse-toggle']");
                return button && button.getAttribute("data-tip") === "Collapse sidebar";
            }""",
            timeout=5000,
        )

        run_htmx_ajax_and_wait(
            authed_page,
            "/htmx/dashboard/download-exceptions-panel",
            "#dashboard-download-exceptions-region",
        )

        assert authed_page.locator("[data-testid='app-header']").count() == 1
        assert dashboard.page_root.is_visible()
        assert dashboard.download_exceptions_panel.is_visible()
        assert dashboard.recent_activity.is_visible()

    def test_dashboard_recent_activity_refresh_keeps_shell_stable(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        dashboard = DashboardPage(authed_page, seeded_server)
        dashboard.goto()

        run_htmx_ajax_and_wait(
            authed_page,
            "/htmx/dashboard/recent-activity",
            "#dashboard-recent-activity-region",
        )

        assert dashboard.page_root.is_visible()
        assert dashboard.recent_activity.is_visible()
        assert dashboard.footer_dock.is_visible()

    def test_dashboard_header_uses_plain_page_header_rail(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        dashboard = DashboardPage(authed_page, seeded_server)
        dashboard.goto()

        mission_box = dashboard.mission_control.bounding_box()
        scoreboard_box = dashboard.scoreboard.bounding_box()
        styles = dashboard.mission_control.evaluate(
            """el => {
                const s = window.getComputedStyle(el);
                return {
                    borderTopWidth: s.borderTopWidth,
                    borderRadius: s.borderTopLeftRadius,
                    boxShadow: s.boxShadow,
                };
            }"""
        )

        assert mission_box is not None
        assert scoreboard_box is not None
        assert abs(mission_box["x"] - scoreboard_box["x"]) < 2
        assert (
            abs(
                (mission_box["x"] + mission_box["width"])
                - (scoreboard_box["x"] + scoreboard_box["width"])
            )
            < 2
        )
        assert styles["borderTopWidth"] == "0px"
        assert styles["borderRadius"] == "0px"
        assert styles["boxShadow"] == "none"

    def test_dashboard_gauges_align_inline_with_header_copy_on_desktop(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        authed_page.set_viewport_size({"width": 1440, "height": 1200})

        dashboard = DashboardPage(authed_page, seeded_server)
        dashboard.goto()

        title_box = dashboard.mission_title_block.bounding_box()
        gauges_box = dashboard.mission_gauges.bounding_box()
        summary_box = dashboard.mission_summary.bounding_box()

        assert title_box is not None
        assert gauges_box is not None
        assert summary_box is not None
        assert gauges_box["x"] > title_box["x"] + title_box["width"] - 1
        assert abs(gauges_box["y"] - title_box["y"]) < 24
        assert gauges_box["x"] + gauges_box["width"] <= summary_box["x"] + summary_box["width"] + 1
