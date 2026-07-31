"""Focused browser coverage for the standardized intervention page."""

from __future__ import annotations

import pytest

from tests.e2e.conftest import wait_for_htmx
from tests.e2e.pages.intervention import InterventionPage
from tests.e2e.pages.series_list import SeriesListPage

pytestmark = pytest.mark.e2e


class TestInterventionPage:
    """Behavior-first E2E checks for the intervention shell."""

    def test_intervention_renders_stable_shell(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        intervention = InterventionPage(authed_page, seeded_server)
        intervention.goto()

        assert intervention.page_root.is_visible()
        assert intervention.shell.is_visible()
        assert intervention.tabs.is_visible()
        assert intervention.content.is_visible()
        assert intervention.summary_cards.is_visible()
        assert intervention.results.is_visible()
        assert intervention.list_region.is_visible()
        assert intervention.queue_tab.get_attribute("aria-current") == "page"
        assert intervention.item_by_text("Alt Source").is_visible()

    def test_intervention_selection_toolbar_and_results_refresh_keep_shell_stable(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        intervention = InterventionPage(authed_page, seeded_server)
        intervention.goto()

        intervention.select_mode_toggle.click()
        intervention.select_visible_button.click()
        assert intervention.bulk_toolbar.is_visible()
        assert intervention.bulk_toolbar.locator("text=1 selected").is_visible()
        assert intervention.bulk_approve_button.inner_text().strip() == "Approve selected"
        assert intervention.bulk_reject_button.inner_text().strip() == "Reject selected"

        authed_page.evaluate(
            """() => {
                htmx.ajax('GET', '/intervention?tab=queue', {
                    target: '#intervention-queue-results',
                    swap: 'outerHTML'
                });
            }"""
        )
        wait_for_htmx(authed_page)

        assert authed_page.locator("[data-testid='intervention-page']").count() == 1
        assert authed_page.locator("[data-testid='intervention-queue-results']").count() == 1
        assert authed_page.locator("[data-testid='intervention-results']").count() == 1
        assert intervention.page_root.is_visible()
        assert intervention.content.is_visible()
        assert intervention.results.is_visible()
        assert intervention.item_by_text("Alt Source").is_visible()

    def test_intervention_queue_matches_series_toolbar_spacing_and_sticky_contract(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        series = SeriesListPage(authed_page, seeded_server)
        series.goto()

        series_geometry = authed_page.evaluate(
            """() => {
                const appHeader = document.querySelector("[data-testid='app-header']");
                const header = document.querySelector("[data-testid='series-registry-header']");
                const toolbar = document.querySelector("[data-testid='series-toolbar']");
                if (!appHeader || !header || !toolbar) {
                    return null;
                }
                const appHeaderRect = appHeader.getBoundingClientRect();
                const headerRect = header.getBoundingClientRect();
                const toolbarRect = toolbar.getBoundingClientRect();
                const content = document.querySelector("#content");
                if (content) {
                    content.scrollTop = 480;
                    content.dispatchEvent(new Event("scroll"));
                } else {
                    window.scrollTo(0, 480);
                }
                const stickyTop = toolbar.getBoundingClientRect().top;
                return {
                    headerOffset: headerRect.top - appHeaderRect.bottom,
                    toolbarGap: toolbarRect.top - headerRect.bottom,
                    stickyTop,
                };
            }"""
        )

        intervention = InterventionPage(authed_page, seeded_server)
        intervention.goto()

        intervention.select_mode_toggle.click()
        assert intervention.bulk_toolbar.is_visible()
        assert intervention.bulk_toolbar.inner_text().strip() == "0 selected"

        intervention_geometry = authed_page.evaluate(
            """() => {
                const appHeader = document.querySelector("[data-testid='app-header']");
                const header = document.querySelector("[data-testid='intervention-header']");
                const toolbar = document.querySelector("[data-testid='intervention-filters']");
                if (!appHeader || !header || !toolbar) {
                    return null;
                }
                const appHeaderRect = appHeader.getBoundingClientRect();
                const headerRect = header.getBoundingClientRect();
                const toolbarRect = toolbar.getBoundingClientRect();
                const content = document.querySelector("#content");
                if (content) {
                    content.scrollTop = 480;
                    content.dispatchEvent(new Event("scroll"));
                } else {
                    window.scrollTo(0, 480);
                }
                const stickyTop = toolbar.getBoundingClientRect().top;
                return {
                    headerOffset: headerRect.top - appHeaderRect.bottom,
                    toolbarGap: toolbarRect.top - headerRect.bottom,
                    stickyTop,
                };
            }"""
        )

        assert series_geometry is not None
        assert intervention_geometry is not None
        assert abs(intervention_geometry["headerOffset"] - series_geometry["headerOffset"]) <= 2
        assert abs(intervention_geometry["toolbarGap"] - series_geometry["toolbarGap"]) <= 2
        assert abs(intervention_geometry["stickyTop"] - series_geometry["stickyTop"]) <= 2

    def test_intervention_history_wrapper_allows_filter_panels_to_escape_table_bounds(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        intervention = InterventionPage(authed_page, seeded_server)
        intervention.goto()
        intervention.history_tab.click()
        intervention.history_panel.wait_for(state="visible", timeout=5000)

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

    def test_intervention_history_details_toggle_tracks_the_visible_row(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        intervention = InterventionPage(authed_page, seeded_server)
        intervention.goto()
        intervention.history_tab.click()
        intervention.history_panel.wait_for(state="visible", timeout=5000)

        toggle = intervention.first_history_details_toggle
        chevron = toggle.locator("svg")
        detail_rows = intervention.history_panel.locator(
            "[data-testid='intervention-history-detail-content']"
        )

        assert toggle.get_attribute("aria-expanded") == "false"
        assert "rotate-180" not in (chevron.get_attribute("class") or "")
        assert detail_rows.count() == 0

        toggle.click()
        wait_for_htmx(authed_page)
        intervention.first_history_detail.wait_for(state="visible", timeout=5000)
        assert toggle.get_attribute("aria-expanded") == "true"
        assert "rotate-180" in (chevron.get_attribute("class") or "")
        assert detail_rows.count() == 1

        toggle.click()
        authed_page.wait_for_function(
            "() => !document.querySelector('[data-testid=intervention-history-detail-content]')"
        )
        assert toggle.get_attribute("aria-expanded") == "false"
        assert "rotate-180" not in (chevron.get_attribute("class") or "")

        toggle.click()
        wait_for_htmx(authed_page)
        intervention.first_history_detail.wait_for(state="visible", timeout=5000)
        assert toggle.get_attribute("aria-expanded") == "true"
        assert detail_rows.count() == 1

    def test_intervention_queue_table_keeps_actions_reachable_on_narrow_viewport(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        authed_page.set_viewport_size({"width": 900, "height": 900})

        intervention = InterventionPage(authed_page, seeded_server)
        intervention.goto()

        geometry = authed_page.evaluate(
            """() => {
                const wrap = document.querySelector("[data-testid='intervention-queue-table']").closest(".series-mission-control-table-wrap");
                const rejectButton = document.querySelector("[data-testid^='intervention-reject-']");
                if (!wrap || !rejectButton) {
                    return null;
                }
                wrap.scrollLeft = wrap.scrollWidth;
                const wrapRect = wrap.getBoundingClientRect();
                const buttonRect = rejectButton.getBoundingClientRect();
                return {
                    clientWidth: wrap.clientWidth,
                    scrollWidth: wrap.scrollWidth,
                    scrollLeft: wrap.scrollLeft,
                    buttonRight: buttonRect.right,
                    wrapRight: wrapRect.right,
                };
            }"""
        )

        assert geometry is not None
        assert geometry["scrollWidth"] > geometry["clientWidth"]
        assert geometry["scrollLeft"] > 0
        assert geometry["buttonRight"] <= geometry["wrapRight"] + 2
