"""Focused browser coverage for the rewritten health shell."""

from __future__ import annotations

import pytest

from tests.e2e.pages.health import HealthPage

pytestmark = pytest.mark.e2e


class TestHealthPage:
    """Behavior-first E2E checks for the health shell."""

    def test_health_renders_stable_shell(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        health = HealthPage(authed_page, seeded_server)
        health.goto()

        assert health.page_root.is_visible()
        assert health.mission_control.is_visible()
        assert health.refresh_button.is_visible()
        assert health.scoreboard.is_visible()
        assert health.component_registry.is_visible()
        assert health.footer_dock.is_visible()
        assert health.status_region.is_visible()
        assert health.get_component_count() >= 1

    def test_health_manual_refresh_keeps_shell_stable(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        health = HealthPage(authed_page, seeded_server)
        health.goto()

        with (
            authed_page.expect_response(
                lambda response: (
                    response.url.endswith("/api/v1/health/refresh")
                    and response.request.method == "POST"
                )
            ) as refresh_info,
            authed_page.expect_response(
                lambda response: (
                    response.url.endswith("/health/status") and response.request.method == "GET"
                )
            ) as status_info,
        ):
            health.refresh_button.click()

        assert refresh_info.value.status == 200
        assert status_info.value.status == 200

        assert health.page_root.is_visible()
        assert authed_page.locator("[data-testid='health-page']").count() == 1
        assert authed_page.locator("[data-testid='health-mission-control']").count() == 1
        assert authed_page.locator("[data-testid='health-status-region']").count() == 1
        assert health.get_toast_message() != "Health refresh failed."

    def test_health_page_emits_no_page_errors(
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

        health = HealthPage(authed_page, seeded_server)
        health.goto()
        with (
            authed_page.expect_response(
                lambda response: (
                    response.url.endswith("/api/v1/health/refresh")
                    and response.request.method == "POST"
                )
            ),
            authed_page.expect_response(
                lambda response: (
                    response.url.endswith("/health/status") and response.request.method == "GET"
                )
            ),
        ):
            health.refresh_button.click()

        assert health.page_root.is_visible()
        assert not errors
        assert not any("Cannot read properties of null" in message for message in console_messages)
        assert not any("refreshing is not defined" in message for message in console_messages)

    def test_health_auto_refresh_keeps_region_alpine_scope_intact(
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

        health = HealthPage(authed_page, seeded_server)
        health.goto()

        with authed_page.expect_response(
            lambda response: (
                response.url.endswith("/health/status") and response.request.method == "GET"
            )
        ) as status_info:
            authed_page.evaluate(
                """
                () => {
                  const region = document.getElementById("health-status-region");
                  if (!region) throw new Error("missing health status region");
                  htmx.trigger(region, "refresh");
                }
                """
            )

        assert status_info.value.status == 200
        assert health.status_region.is_visible()
        assert not errors
        assert not any("refreshing is not defined" in message for message in console_messages)

    def test_health_component_card_navigates_to_detail_page(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        health = HealthPage(authed_page, seeded_server)
        health.goto()

        health.first_component_card.click()
        authed_page.wait_for_url("**/health/*", timeout=5000)

        assert health.component_page_root.is_visible()
        assert health.detail_back_link.is_visible()
        assert authed_page.locator("[data-testid^='health-component-detail-']").first.is_visible()

    def test_download_clients_card_navigates_to_registry_page(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        health = HealthPage(authed_page, seeded_server)
        health.goto()

        health.component_card("download_clients").click()
        authed_page.wait_for_url("**/health/download_clients", timeout=5000)

        assert authed_page.locator("[data-testid='health-download-clients-page']").is_visible()
        assert authed_page.locator("[data-testid='health-download-clients-table']").is_visible()

    def test_indexers_card_navigates_to_registry_page(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        health = HealthPage(authed_page, seeded_server)
        health.goto()

        health.component_card("indexers").click()
        authed_page.wait_for_url("**/health/indexers", timeout=5000)

        assert authed_page.locator("[data-testid='health-indexers-page']").is_visible()
        assert authed_page.locator("[data-testid='health-indexers-table']").is_visible()

    def test_health_overview_stat_tiles_fit_content_without_clipping(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        health = HealthPage(authed_page, seeded_server)
        health.goto()

        metrics = authed_page.evaluate(
            """
            () => {
              const tiles = Array.from(document.querySelectorAll('.health-component-card__stat'));
              return tiles.map((tile) => {
                const rect = tile.getBoundingClientRect();
                return {
                  text: tile.innerText,
                  height: Math.round(rect.height),
                  clientHeight: tile.clientHeight,
                  scrollHeight: tile.scrollHeight,
                  lineCount: tile.innerText.split('\\n').filter(Boolean).length,
                };
              });
            }
            """
        )

        assert metrics
        assert all(item["scrollHeight"] <= item["clientHeight"] for item in metrics), metrics

        multiline_tiles = [item for item in metrics if item["lineCount"] >= 3]
        single_line_tiles = [item for item in metrics if item["lineCount"] <= 2]

        if multiline_tiles and single_line_tiles:
            assert min(item["height"] for item in multiline_tiles) > min(
                item["height"] for item in single_line_tiles
            ), metrics

    def test_health_detail_page_stays_stable_across_status_refresh(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        health = HealthPage(authed_page, seeded_server)
        health.goto()

        health.first_component_card.click()
        authed_page.wait_for_url("**/health/*", timeout=5000)
        detail_panel = authed_page.locator("[data-testid^='health-component-detail-']").first
        detail_panel.wait_for(state="visible", timeout=5000)
        detail_testid = detail_panel.get_attribute("data-testid")
        assert detail_testid is not None

        with authed_page.expect_response(
            lambda response: (
                "/health/" in response.url
                and response.url.endswith("/status")
                and response.request.method == "GET"
            )
        ) as status_info:
            authed_page.evaluate(
                """
                () => {
                  const region = document.getElementById("health-component-status-region");
                  if (!region) throw new Error("missing health status region");
                  const path = window.location.pathname + window.location.search;
                  const partialPath = path.endsWith("/status") ? path : `${path}/status`;
                  htmx.ajax("GET", partialPath, {
                    target: "#health-component-status-region",
                    swap: "outerHTML",
                  });
                }
                """
            )

        assert status_info.value.status == 200
        authed_page.locator(f"[data-testid='{detail_testid}']").wait_for(
            state="visible", timeout=5000
        )
        assert authed_page.locator(f"[data-testid='{detail_testid}']").is_visible()

    def test_health_detail_recheck_refreshes_only_the_active_component(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        health = HealthPage(authed_page, seeded_server)
        health.goto()

        health.component_card("database").click()
        authed_page.wait_for_url("**/health/database", timeout=5000)

        with (
            authed_page.expect_response(
                lambda response: (
                    response.url.endswith("/api/v1/health/database/refresh")
                    and response.request.method == "POST"
                )
            ) as refresh_info,
            authed_page.expect_response(
                lambda response: (
                    response.url.endswith("/health/database/status")
                    and response.request.method == "GET"
                )
            ) as status_info,
        ):
            health.detail_refresh_button.click()

        assert refresh_info.value.status == 200
        assert status_info.value.status == 200
        assert authed_page.locator("[data-testid='health-component-detail-database']").is_visible()

    def test_database_detail_page_shows_database_check_suite(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        health = HealthPage(authed_page, seeded_server)
        health.goto()

        health.component_card("database").click()
        authed_page.wait_for_url("**/health/database", timeout=5000)

        assert authed_page.locator(
            ".health-check-row__name", has_text="Connection round trip"
        ).first.is_visible()
        assert authed_page.locator(
            ".health-check-row__name", has_text="Query latency"
        ).first.is_visible()

    def test_system_overview_card_shows_cpu_and_memory_stats(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        health = HealthPage(authed_page, seeded_server)
        health.goto()

        with (
            authed_page.expect_response(
                lambda response: (
                    response.url.endswith("/api/v1/health/refresh")
                    and response.request.method == "POST"
                )
            ) as refresh_info,
            authed_page.expect_response(
                lambda response: (
                    response.url.endswith("/health/status") and response.request.method == "GET"
                )
            ) as status_info,
        ):
            health.refresh_button.click()

        assert refresh_info.value.status == 200
        assert status_info.value.status == 200

        system_card = authed_page.locator("[data-testid='health-component-card-system']")
        assert system_card.is_visible()
        assert system_card.locator(
            ".health-component-card__stat-label", has_text="CPU"
        ).is_visible()
        assert system_card.locator(
            ".health-component-card__stat-label", has_text="Memory"
        ).is_visible()
        assert system_card.locator(".health-component-card__stat-value", has_text="—").count() < 2

    def test_health_detail_history_supports_sort_and_search(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        health = HealthPage(authed_page, seeded_server)
        health.goto()

        health.first_component_card.click()
        authed_page.wait_for_url("**/health/*", timeout=5000)

        with authed_page.expect_response(
            lambda response: (
                "/health/" in response.url
                and "/status?sort=-check_name" in response.url
                and response.request.method == "GET"
            )
        ):
            authed_page.locator("[data-testid='health-history-sort-check_name']").click()

        authed_page.wait_for_url("**/health/*?sort=-check_name", timeout=5000)
        assert authed_page.locator("[data-testid='health-history-toolbar']").is_visible()

        search_input = authed_page.locator("[data-testid='health-history-search-input']")
        with authed_page.expect_response(
            lambda response: (
                "/health/" in response.url
                and "/status?" in response.url
                and "search=zzzz-no-match-health-history" in response.url
                and response.request.method == "GET"
            )
        ):
            search_input.fill("zzzz-no-match-health-history")

        authed_page.locator("text=No matching history").wait_for(state="visible", timeout=5000)

        with authed_page.expect_response(
            lambda response: (
                "/health/" in response.url
                and "/status?sort=-check_name" in response.url
                and "search=" not in response.url
                and response.request.method == "GET"
            )
        ):
            search_input.fill("")

        authed_page.locator("text=No matching history").wait_for(state="hidden", timeout=5000)
        assert authed_page.locator("[data-testid='health-component-detail-page']").count() == 1
        assert authed_page.locator("[data-testid='health-component-status-region']").count() == 1
        assert authed_page.locator("[data-testid='health-history-results']").count() == 1
