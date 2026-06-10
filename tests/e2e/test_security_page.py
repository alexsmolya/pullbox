"""Focused browser coverage for the rewritten security shell."""

from __future__ import annotations

import pytest

from tests.e2e.pages.security import SecurityPage

pytestmark = pytest.mark.e2e


class TestSecurityPage:
    """Behavior-first E2E checks for the security shell."""

    def test_security_renders_stable_shell(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        security = SecurityPage(authed_page, seeded_server)
        security.goto()

        assert security.page_root.is_visible()
        assert security.header.is_visible()
        assert security.page_title.is_visible()
        assert security.body.is_visible()
        assert security.tabs.is_visible()
        assert security.content.is_visible()
        assert security.footer_dock.is_visible()
        assert security.panel("authentication").is_visible()
        assert authed_page.locator(
            "[data-testid='security-authentication-access-model-card']"
        ).is_visible()
        assert security.tab("authentication").get_attribute("aria-current") == "page"

    def test_security_header_matches_series_header_contract(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        security = SecurityPage(authed_page, seeded_server)
        security.goto()

        security_title = authed_page.locator("[data-testid='security-page-title']").first
        security_subtitle = authed_page.locator("[data-testid='security-page-subtitle']").first

        security_title_style = security_title.evaluate(
            """
            node => {
              const style = window.getComputedStyle(node);
              return {
                fontFamily: style.fontFamily,
                fontSize: style.fontSize,
                fontWeight: style.fontWeight,
                letterSpacing: style.letterSpacing,
                lineHeight: style.lineHeight,
                textTransform: style.textTransform,
              };
            }
            """
        )
        security_subtitle_style = security_subtitle.evaluate(
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

        authed_page.goto(f"{seeded_server}/series")
        authed_page.wait_for_load_state("networkidle")

        series_title = authed_page.locator("[data-testid='series-registry-title']").first
        series_subtitle = authed_page.locator("[data-testid='series-registry-subtitle']").first

        series_title_style = series_title.evaluate(
            """
            node => {
              const style = window.getComputedStyle(node);
              return {
                fontFamily: style.fontFamily,
                fontSize: style.fontSize,
                fontWeight: style.fontWeight,
                letterSpacing: style.letterSpacing,
                lineHeight: style.lineHeight,
                textTransform: style.textTransform,
              };
            }
            """
        )
        series_subtitle_style = series_subtitle.evaluate(
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

        assert security_title_style == series_title_style
        assert security_subtitle_style == series_subtitle_style

    def test_security_tab_switch_keeps_shell_stable(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        security = SecurityPage(authed_page, seeded_server)
        security.goto()

        security.switch_tab("file_safety")

        assert security.page_root.is_visible()
        assert authed_page.locator("[data-testid='security-page']").count() == 1
        assert authed_page.locator("[data-testid='security-body']").count() == 1
        assert authed_page.locator("[data-testid='security-tabs']").count() == 1
        assert authed_page.locator("[data-testid='security-content']").count() == 1
        assert security.footer_dock.is_visible()
        assert security.panel("file_safety").is_visible()
        assert security.tab("file_safety").get_attribute("aria-current") == "page"

        security.switch_tab("audit_log")

        assert security.page_root.is_visible()
        assert authed_page.locator("[data-testid='security-page']").count() == 1
        assert authed_page.locator("[data-testid='security-body']").count() == 1
        assert authed_page.locator("[data-testid='security-tabs']").count() == 1
        assert authed_page.locator("[data-testid='security-content']").count() == 1
        assert security.footer_dock.is_visible()
        assert security.panel("audit_log").is_visible()
        assert authed_page.locator("[data-testid='security-audit-log-events-card']").is_visible()
        assert security.tab("audit_log").get_attribute("aria-current") == "page"

    def test_security_card_footer_keeps_clearance_above_page_dock(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        security = SecurityPage(authed_page, seeded_server)
        security.goto()

        gap = authed_page.evaluate(
            """
            () => {
              const content = document.querySelector("#content");
              const pageDock = document.querySelector("#page-footer-dock");
              const cardFooters = Array.from(document.querySelectorAll(".settings-footer"));
              const lastCardFooter = cardFooters.at(-1);
              if (!content || !pageDock || !lastCardFooter) return null;
              content.scrollTop = content.scrollHeight;
              const footerBox = lastCardFooter.getBoundingClientRect();
              const dockBox = pageDock.getBoundingClientRect();
              return dockBox.top - footerBox.bottom;
            }
            """
        )

        assert gap is not None
        assert gap >= 12

    def test_security_first_cards_align_to_same_top_rail(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        security = SecurityPage(authed_page, seeded_server)
        security.goto()

        auth_card = authed_page.locator(
            "[data-testid='security-authentication-access-model-card']"
        ).first
        auth_box = auth_card.bounding_box()
        assert auth_box is not None

        card_map = {
            "api_access": "[data-testid='security-api-access-registry-card']",
            "file_safety": "[data-testid='security-file-safety-allowlist-card']",
            "audit_log": "[data-testid='security-audit-log-events-card']",
        }

        for tab, selector in card_map.items():
            security.switch_tab(tab)
            target = authed_page.locator(selector).first
            target_box = target.bounding_box()

            assert target_box is not None
            assert abs(target_box["y"] - auth_box["y"]) <= 2, (
                f"{tab} top card y={target_box['y']} does not match auth y={auth_box['y']}"
            )

    def test_security_direct_tab_load_renders_matching_panel(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        security = SecurityPage(authed_page, seeded_server)
        security.goto("api_access")

        assert security.page_root.is_visible()
        assert security.panel("api_access").is_visible()
        assert security.tab("api_access").get_attribute("aria-current") == "page"

    def test_security_tab_switch_resets_scroll_to_top(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        security = SecurityPage(authed_page, seeded_server)
        security.goto("file_safety")

        authed_page.evaluate(
            """
            () => {
              const content = document.getElementById("content");
              if (content) {
                content.scrollTop = Math.max(600, content.scrollHeight);
                content.dispatchEvent(new Event("scroll"));
              }
            }
            """
        )
        authed_page.wait_for_function(
            """() => {
                const content = document.getElementById("content");
                return !!content && content.scrollTop > 0;
            }""",
            timeout=5000,
        )

        security.switch_tab("authentication")

        authed_page.wait_for_function(
            """() => {
                const content = document.getElementById("content");
                return !!content && content.scrollTop === 0;
            }""",
            timeout=5000,
        )

    def test_security_tab_switches_emit_no_password_form_warnings(
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

        security = SecurityPage(authed_page, seeded_server)
        security.goto()

        security.switch_tab("api_access")
        security.switch_tab("file_safety")
        security.switch_tab("audit_log")
        security.switch_tab("authentication")

        assert security.page_root.is_visible()
        assert not errors
        assert not any(
            "Password field is not contained in a form" in message for message in console_messages
        )
        assert not any("Password forms should have" in message for message in console_messages)
        assert not any(
            "Multiple forms should be contained in their own form elements" in message
            for message in console_messages
        )

    def test_security_audit_log_dropdown_filters_events(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        security = SecurityPage(authed_page, seeded_server)
        security.goto()
        security.switch_tab("audit_log")

        with authed_page.expect_response(
            lambda response: "event_type=login_failure" in response.url
        ):
            security.select_audit_type("login_failure")

        assert security.dropdown_label("security-audit-type-select") == "Login Failure"

    def test_security_audit_log_footer_values_clear_when_switching_to_non_audit_tab(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        security = SecurityPage(authed_page, seeded_server)
        security.goto()
        security.switch_tab("audit_log")

        audit_footer_status = authed_page.locator(
            "[data-testid='security-footer-dock'] [data-testid='page-dock-status']"
        ).first
        audit_footer_status.wait_for(state="visible", timeout=5000)

        security.switch_tab("file_safety")

        authed_page.wait_for_function(
            """() => !document.querySelector("[data-testid='security-footer-dock'] [data-testid='page-dock-status']")"""
        )
        assert (
            authed_page.locator(
                "[data-testid='security-footer-dock'] [data-testid='page-dock-status']"
            ).count()
            == 0
        )

    def test_security_file_safety_allowlist_actions_autosave_without_footer_row(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        security = SecurityPage(authed_page, seeded_server)
        security.goto("file_safety")

        allowlist_card = authed_page.locator(
            "[data-testid='security-file-safety-allowlist-card']"
        ).first
        assert allowlist_card.get_by_role("button", name="Save Allowlist").count() == 0

        extension_input = authed_page.locator(
            "[data-testid='security-file-safety-extension-input']"
        ).first
        extension_input.fill("mobi")

        with authed_page.expect_response(
            lambda response: response.request.method == "PUT" and "/api/v1/config" in response.url
        ):
            authed_page.locator("[data-testid='security-file-safety-add-extension']").click()

        mobi_pill = allowlist_card.locator(".pill", has_text=".mobi").first
        assert mobi_pill.is_visible()

        with authed_page.expect_response(
            lambda response: response.request.method == "PUT" and "/api/v1/config" in response.url
        ):
            mobi_pill.get_by_role("button").click()

        assert mobi_pill.count() == 0

        with authed_page.expect_response(
            lambda response: response.request.method == "PUT" and "/api/v1/config" in response.url
        ):
            authed_page.locator("[data-testid='security-file-safety-reset-extensions']").click()

    def test_security_file_safety_dangerous_toggle_autosaves_and_archive_save_tracks_dirty_state(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        security = SecurityPage(authed_page, seeded_server)
        security.goto("file_safety")

        dangerous_card = authed_page.locator(
            "[data-testid='security-file-safety-dangerous-card']"
        ).first
        archive_input = authed_page.locator(
            "[data-testid='security-file-safety-archive-limit-input']"
        ).first
        archive_save = authed_page.locator(
            "[data-testid='security-file-safety-save-archive']"
        ).first

        assert dangerous_card.get_by_role("button", name="Save Dangerous Detection").count() == 0
        assert archive_save.is_disabled()

        toggle = authed_page.locator("[data-testid='security-file-safety-dangerous-toggle']").first

        with authed_page.expect_response(
            lambda response: response.request.method == "PUT" and "/api/v1/config" in response.url
        ):
            toggle.uncheck(force=True)

        assert archive_save.is_disabled()

        archive_input.fill("2500")
        assert archive_save.is_enabled()

        with authed_page.expect_response(
            lambda response: response.request.method == "PUT" and "/api/v1/config" in response.url
        ):
            archive_save.click()

        assert archive_save.is_disabled()
