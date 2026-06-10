"""Focused browser coverage for the first-run setup shell."""

from __future__ import annotations

import httpx
import pytest
from playwright.sync_api import expect

from tests.e2e.pages.setup_wizard import SetupWizardPage

pytestmark = pytest.mark.e2e


class TestSetupWizardPage:
    """Behavior-first checks for the standalone setup shell."""

    def test_setup_wizard_loads_clean_shell(
        self,
        page,
        first_run_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        """The /setup route renders the first-run setup shell on a pristine server."""
        page_errors: list[str] = []
        asset_failures: list[str] = []

        page.on("pageerror", lambda exc: page_errors.append(str(exc)))

        def _capture_failed_assets(response) -> None:  # type: ignore[no-untyped-def]
            if response.request.resource_type not in {"stylesheet", "script"}:
                return
            if response.status >= 400:
                asset_failures.append(f"{response.status} {response.url}")

        page.on("response", _capture_failed_assets)

        setup_status = httpx.get(
            f"{first_run_server}/setup",
            timeout=5.0,
            follow_redirects=False,
        )
        assert setup_status.status_code == 200

        setup = SetupWizardPage(page, first_run_server)
        page.goto(f"{first_run_server}/setup")
        setup.page_root.wait_for(state="visible", timeout=5000)
        assert setup.page_root.is_visible()
        assert setup.shell.is_visible()
        assert setup.card.is_visible()

        assert not page_errors
        assert not asset_failures

    def test_setup_wizard_page_renders_immediately_without_setup_boot_splash(
        self,
        page,
        first_run_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        """Setup should render directly without a setup-page bootstrap overlay."""

        setup = SetupWizardPage(page, first_run_server)
        page.goto(f"{first_run_server}/setup", wait_until="commit")
        expect(page.get_by_test_id("setup-boot-splash")).to_have_count(0)
        page.wait_for_function(
            "() => document.body && getComputedStyle(document.body).visibility === 'visible'",
            timeout=1200,
        )

        assert setup.page_root.is_visible()

    def test_setup_wizard_renders_current_shell_without_framework_assets(
        self,
        page,
        first_run_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        """First-run setup should paint without requesting Tailwind, Alpine, or pullbox.js."""

        framework_requests: list[str] = []

        def _capture_request(request) -> None:  # type: ignore[no-untyped-def]
            url = request.url
            if any(
                asset in url
                for asset in (
                    "/static/css/tailwind.css",
                    "/static/js/alpine.min.js",
                    "/static/js/pullbox.js",
                )
            ):
                framework_requests.append(url)

        page.on("request", _capture_request)

        setup = SetupWizardPage(page, first_run_server)
        page.goto(f"{first_run_server}/setup", wait_until="domcontentloaded")

        setup.page_root.wait_for(state="visible", timeout=1200)
        setup.shell.wait_for(state="visible", timeout=1200)
        setup.card.wait_for(state="visible", timeout=1200)
        page.get_by_test_id("setup-hero-block").wait_for(state="visible", timeout=1200)
        expect(page.get_by_text("Create your first account.")).to_be_visible()
        shell_styles = page.evaluate(
            """() => {
                const card = document.querySelector('[data-testid="setup-card"]');
                if (!card) {
                    return null;
                }
                const styles = getComputedStyle(card);
                return {
                    radius: styles.borderTopLeftRadius,
                    background: styles.backgroundColor,
                    borderTopWidth: styles.borderTopWidth,
                };
            }"""
        )

        assert shell_styles is not None
        assert shell_styles["radius"] != "0px"
        assert shell_styles["background"] not in {"rgba(0, 0, 0, 0)", "transparent"}
        assert shell_styles["borderTopWidth"] != "0px"
        assert framework_requests == []

    def test_setup_wizard_uses_no_framework_asset_tags_on_first_run(
        self,
        page,
        first_run_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        """First-run setup should not include Tailwind, Alpine, or pullbox.js tags."""

        page.goto(f"{first_run_server}/setup")

        asset_urls = page.evaluate(
            """() => ({
                stylesheet: document.querySelector('link[href*="/static/css/tailwind.css"]')?.href || '',
                alpine: Array.from(document.scripts).map((script) => script.src).find((src) => src.includes('/static/js/alpine.min.js')) || '',
                pullbox: Array.from(document.scripts).map((script) => script.src).find((src) => src.includes('/static/js/pullbox.js')) || '',
            })"""
        )

        assert asset_urls["stylesheet"] == ""
        assert asset_urls["alpine"] == ""
        assert asset_urls["pullbox"] == ""

    def test_setup_wizard_omits_old_side_step_tracker(
        self,
        page,
        first_run_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        """Desktop setup should no longer render the old six-step tracker."""

        page.set_viewport_size({"width": 1280, "height": 900})
        page.goto(f"{first_run_server}/setup")

        expect(page.get_by_test_id("setup-side-steps")).to_have_count(0)
        expect(page.get_by_text("Library root")).to_have_count(0)
        expect(page.get_by_text("ComicVine")).to_have_count(0)
        expect(page.get_by_text("Download client")).to_have_count(0)
        expect(page.get_by_text("Search sources")).to_have_count(0)
        expect(page.get_by_text("Step 1 of 6")).to_have_count(0)

    def test_root_navigation_renders_setup_directly(
        self,
        page,
        first_run_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        """Root setup navigation should render the setup page without an extra entry shell."""

        page.goto(first_run_server, wait_until="commit")

        expect(page.get_by_test_id("setup-page")).to_be_visible()
        expect(page.get_by_test_id("setup-shell")).to_be_visible()
        expect(page.get_by_test_id("setup-entry-shell")).to_have_count(0)
        expect(page).to_have_url(f"{first_run_server}/setup")

    def test_setup_wizard_headline_stays_single_line_on_standard_desktop_width(
        self,
        page,
        first_run_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        """The setup hero headline should stay on one line on a standard desktop viewport."""

        page.set_viewport_size({"width": 1200, "height": 900})
        page.goto(f"{first_run_server}/setup")

        line_metrics = page.evaluate(
            """() => {
                const el = document.querySelector('.setup-hero-headline');
                const panel = document.querySelector('[data-testid="setup-hero-block"]');
                if (!el) {
                  return null;
                }
                const clone = el.cloneNode(true);
                clone.style.position = 'absolute';
                clone.style.visibility = 'hidden';
                clone.style.whiteSpace = 'nowrap';
                clone.style.width = 'auto';
                clone.style.maxWidth = 'none';
                clone.style.display = 'inline-block';
                clone.style.left = '-99999px';
                document.body.appendChild(clone);
                const neededWidth = clone.getBoundingClientRect().width;
                clone.remove();

                return {
                  neededWidth,
                  panelWidth: panel ? panel.getBoundingClientRect().width : 0,
                };
            }"""
        )

        assert line_metrics is not None
        assert line_metrics["neededWidth"] <= line_metrics["panelWidth"] + 1
