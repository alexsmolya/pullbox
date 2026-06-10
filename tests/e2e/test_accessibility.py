"""Automated WCAG 2.2 AA coverage for representative Pullbox flows."""

from __future__ import annotations

import pytest

from tests.e2e.accessibility import assert_no_axe_violations
from tests.e2e.conftest import wait_for_htmx

pytestmark = [pytest.mark.e2e, pytest.mark.accessibility]


def test_login_page_has_no_wcag_aa_violations(
    page,
    seeded_server: str,  # type: ignore[no-untyped-def]
) -> None:
    page.goto(f"{seeded_server}/login")
    page.locator("[data-testid='login-page']").first.wait_for(state="visible", timeout=5000)
    page.wait_for_load_state("networkidle")
    wait_for_htmx(page)

    assert_no_axe_violations(
        page,
        name="page /login",
        include=["main"],
        exclude=["#toast-container", ".htmx-indicator"],
    )


@pytest.mark.parametrize(
    ("path", "ready_selector"),
    [
        ("/", "[data-testid='dashboard-page']"),
        ("/settings?tab=general", "[data-testid='settings-page']"),
        ("/security?tab=authentication", "[data-testid='security-page']"),
        ("/system?tab=tasks", "[data-testid='system-page']"),
        ("/health", "[data-testid='health-page']"),
        ("/downloads?tab=queue", "[data-testid='downloads-page']"),
        ("/post-processing?tab=queue", "[data-testid='post-processing-page']"),
        ("/import", "[data-testid='import-page']"),
        ("/library", "[data-testid='library-page']"),
        ("/series/1", "[data-testid='series-detail-page']"),
        ("/issues/1", "[data-testid='issue-detail-page']"),
        ("/utilities/permissions", "[data-testid='utilities-permissions-page']"),
    ],
)
def test_authenticated_pages_have_no_wcag_aa_violations(
    authed_page,
    seeded_server: str,  # type: ignore[no-untyped-def]
    path: str,
    ready_selector: str,
) -> None:
    authed_page.goto(f"{seeded_server}{path}")
    authed_page.locator(ready_selector).first.wait_for(state="visible", timeout=5000)
    if path.startswith("/import"):
        authed_page.wait_for_load_state("domcontentloaded")
    else:
        authed_page.wait_for_load_state("networkidle")
    wait_for_htmx(authed_page)

    assert_no_axe_violations(
        authed_page,
        name=f"page {path}",
        include=["main"],
        exclude=["#toast-container", ".htmx-indicator"],
    )


def test_settings_confirm_modal_has_no_wcag_aa_violations(
    authed_page,
    seeded_server: str,  # type: ignore[no-untyped-def]
) -> None:
    authed_page.goto(f"{seeded_server}/settings?tab=utilities")
    authed_page.locator("[data-testid='settings-page']").first.wait_for(
        state="visible", timeout=5000
    )
    authed_page.locator("[data-testid='settings-utilities-empty-trash-now']").click()

    authed_page.locator("#pb-confirm-title").wait_for(state="visible", timeout=5000)
    authed_page.wait_for_timeout(250)

    assert (
        authed_page.locator("[x-ref='cancelBtn']").first.evaluate(
            "(element) => document.activeElement === element"
        )
        is True
    )

    assert_no_axe_violations(
        authed_page,
        name="settings confirm modal",
        include=["#pb-confirm-dialog", "#pb-confirm-dialog > div"],
    )


def test_settings_dropdown_panel_has_no_wcag_aa_violations(
    authed_page,
    seeded_server: str,  # type: ignore[no-untyped-def]
) -> None:
    authed_page.goto(f"{seeded_server}/settings?tab=ui")
    authed_page.locator("[data-testid='settings-page']").first.wait_for(
        state="visible", timeout=5000
    )

    dropdown_root = authed_page.locator("[data-testid='settings-ui-timezone-select']").first
    dropdown_root.locator("[data-dropdown-select-trigger]").first.click()
    authed_page.locator("[data-dropdown-select-panel]:visible").first.wait_for(
        state="visible", timeout=5000
    )

    assert_no_axe_violations(
        authed_page,
        name="settings timezone dropdown",
        include=["[data-testid='settings-ui-timezone-select']"],
    )


def test_settings_library_permissions_card_has_no_wcag_aa_violations(
    authed_page,
    seeded_server: str,  # type: ignore[no-untyped-def]
) -> None:
    authed_page.goto(f"{seeded_server}/settings?tab=media")
    authed_page.locator("[data-testid='settings-page']").first.wait_for(
        state="visible", timeout=5000
    )

    assert_no_axe_violations(
        authed_page,
        name="settings library permissions card",
        include=["[data-testid='settings-media-library-permissions-card']"],
    )


def test_header_no_longer_renders_live_update_toggle(
    authed_page,
    seeded_server: str,  # type: ignore[no-untyped-def]
) -> None:
    authed_page.goto(f"{seeded_server}/downloads?tab=queue")
    authed_page.locator("[data-testid='downloads-page']").first.wait_for(
        state="visible", timeout=5000
    )

    assert authed_page.locator("[data-testid='live-updates-toggle']").count() == 0
    assert authed_page.evaluate("() => window.pullboxLiveUpdatesEnabled()") is True


def test_live_update_pause_state_still_persists_without_header_control(
    authed_page,
    seeded_server: str,  # type: ignore[no-untyped-def]
) -> None:
    authed_page.goto(f"{seeded_server}/")
    authed_page.locator("[data-testid='dashboard-page']").first.wait_for(
        state="visible", timeout=5000
    )
    authed_page.evaluate(
        """() => {
            localStorage.setItem('pullbox-live-updates', 'paused');
            document.dispatchEvent(new CustomEvent('pullbox:live-updates-changed', { detail: { enabled: false } }));
        }"""
    )
    assert authed_page.evaluate("() => window.pullboxLiveUpdatesEnabled()") is False

    authed_page.goto(f"{seeded_server}/health")
    authed_page.locator("[data-testid='health-page']").first.wait_for(state="visible", timeout=5000)

    assert authed_page.locator("[data-testid='live-updates-toggle']").count() == 0
    assert authed_page.evaluate("() => window.pullboxLiveUpdatesEnabled()") is False
    assert authed_page.evaluate("() => localStorage.getItem('pullbox-live-updates')") == "paused"
