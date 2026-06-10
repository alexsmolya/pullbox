"""Browser regressions for the What's New table sorting contract."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

import pytest

from pullbox.models.whats_new import WhatsNewCacheKind, WhatsNewReleaseCache
from tests.e2e.conftest import wait_for_htmx

pytestmark = pytest.mark.e2e


def _run_async_blocking(coro):  # type: ignore[no-untyped-def]
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict[str, object] = {}
    error: dict[str, BaseException] = {}

    def _runner() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:  # pragma: no cover - bubbles to caller
            error["exc"] = exc

    import threading

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()

    if "exc" in error:
        raise error["exc"]
    return result.get("value")


def _release_summary(
    *,
    locg_issue_id: int,
    display_title: str,
    series_title: str,
    series_id: int,
    publisher_name: str,
    publisher_id: int,
    price: float,
    issue_number: str,
) -> dict[str, object]:
    return {
        "locg_issue_id": locg_issue_id,
        "locg_url": f"https://leagueofcomicgeeks.com/comic/{locg_issue_id}/{display_title.lower().replace(' ', '-')}",
        "title": display_title,
        "display_title": display_title,
        "issue_number": issue_number,
        "store_date": "2026-05-20",
        "price": price,
        "community_rating": 4.0,
        "community_counts": {"pull": 1000},
        "variant_count": 0,
        "cover_url": "https://cdn.example.com/test-cover.jpg",
        "series": {
            "title": series_title,
            "locg_series_id": series_id,
            "locg_url": f"https://leagueofcomicgeeks.com/comics/series/{series_id}/{series_title.lower().replace(' ', '-')}",
            "start_year": 2026,
            "volume": "2026",
        },
        "publisher": {
            "name": publisher_name,
            "locg_publisher_id": publisher_id,
            "excluded": False,
            "excluded_reason": None,
        },
    }


async def _seed_whats_new_current_week() -> None:
    from sqlalchemy import delete

    from pullbox.database import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        await session.execute(delete(WhatsNewReleaseCache))
        session.add(
            WhatsNewReleaseCache(
                cache_key="current-week:2026-05-20",
                cache_kind=WhatsNewCacheKind.CURRENT_WEEK,
                store_date=date(2026, 5, 20),
                payload={
                    "store_date": "2026-05-20",
                    "count": 4,
                    "last_updated": "2026-05-19T12:15:00+00:00",
                    "issues": [
                        _release_summary(
                            locg_issue_id=260001,
                            display_title="Atlas Deluxe #1",
                            series_title="Atlas Deluxe",
                            series_id=960001,
                            publisher_name="Zenith Press",
                            publisher_id=501,
                            price=9.99,
                            issue_number="1",
                        ),
                        _release_summary(
                            locg_issue_id=260002,
                            display_title="Budget Hero #1",
                            series_title="Budget Hero",
                            series_id=960002,
                            publisher_name="Bravo Press",
                            publisher_id=502,
                            price=1.99,
                            issue_number="1",
                        ),
                        _release_summary(
                            locg_issue_id=260003,
                            display_title="Midnight Flight #1",
                            series_title="Midnight Flight",
                            series_id=960003,
                            publisher_name="Alpha Comics",
                            publisher_id=503,
                            price=4.99,
                            issue_number="1",
                        ),
                        _release_summary(
                            locg_issue_id=260004,
                            display_title="Omega Patrol #1",
                            series_title="Omega Patrol",
                            series_id=960004,
                            publisher_name="Alpha Comics",
                            publisher_id=503,
                            price=4.99,
                            issue_number="1",
                        ),
                    ],
                },
                fetched_at=datetime(2026, 5, 19, 12, 0, tzinfo=UTC),
                last_successful_refresh_at=datetime(2026, 5, 19, 12, 0, tzinfo=UTC),
            )
        )
        await session.commit()


def _visible_release_titles(page) -> list[str]:  # type: ignore[no-untyped-def]
    titles = page.locator(
        "[data-testid='whats-new-current-list-view'] [data-testid='whats-new-release-row'] .series-mission-control-name"
    )
    return [title.strip() for title in titles.all_inner_texts()]


class TestWhatsNewPage:
    def test_pagination_resets_whats_new_content_scroll_to_top(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        _run_async_blocking(_seed_whats_new_current_week())

        authed_page.goto(f"{seeded_server}/whats-new?per_page=1")
        authed_page.wait_for_load_state("networkidle")

        scroll_state = authed_page.evaluate(
            """() => {
                const content = document.getElementById("content");
                const results = document.getElementById("whats-new-results-body");
                if (!content || !results) {
                    return null;
                }

                const spacer = document.createElement("div");
                spacer.setAttribute("data-testid", "whats-new-scroll-spacer");
                spacer.style.height = "2400px";
                results.appendChild(spacer);
                content.scrollTop = 480;
                content.dispatchEvent(new Event("scroll"));

                return {
                    before: content.scrollTop,
                    height: content.scrollHeight,
                    clientHeight: content.clientHeight,
                };
            }"""
        )

        assert scroll_state is not None
        assert scroll_state["before"] > 0

        authed_page.locator("#pagination-next").click()
        wait_for_htmx(authed_page)

        after_scroll = authed_page.evaluate(
            """() => {
                const content = document.getElementById("content");
                return content ? content.scrollTop : window.scrollY;
            }"""
        )

        assert "page=2" in authed_page.url
        assert after_scroll == 0

    def test_pagination_next_advances_whats_new_results(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        _run_async_blocking(_seed_whats_new_current_week())

        authed_page.goto(f"{seeded_server}/whats-new?per_page=1")
        authed_page.wait_for_load_state("networkidle")

        assert _visible_release_titles(authed_page) == ["Atlas Deluxe #1"]

        authed_page.locator("#pagination-next").click()
        wait_for_htmx(authed_page)

        assert "page=2" in authed_page.url
        assert "per_page=1" in authed_page.url
        assert _visible_release_titles(authed_page) == ["Budget Hero #1"]

    def test_same_header_click_toggles_whats_new_sort_direction(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        _run_async_blocking(_seed_whats_new_current_week())

        authed_page.goto(f"{seeded_server}/whats-new")
        authed_page.wait_for_load_state("networkidle")

        price_header = authed_page.locator("[data-testid='whats-new-sort-price']").first

        price_header.click()
        wait_for_htmx(authed_page)

        assert "sort=price" in authed_page.url
        assert _visible_release_titles(authed_page)[:2] == [
            "Budget Hero #1",
            "Midnight Flight #1",
        ]
        assert authed_page.locator("#whats-new-sort-input").input_value() == "price"

        price_header = authed_page.locator("[data-testid='whats-new-sort-price']").first
        price_header.click()
        wait_for_htmx(authed_page)

        assert "sort=-price" in authed_page.url
        assert _visible_release_titles(authed_page)[:2] == [
            "Atlas Deluxe #1",
            "Midnight Flight #1",
        ]
        assert authed_page.locator("#whats-new-sort-input").input_value() == "-price"

    def test_repeated_sort_clicks_keep_latest_server_sort_active(
        self,
        authed_page,
        seeded_server: str,  # type: ignore[no-untyped-def]
    ) -> None:
        _run_async_blocking(_seed_whats_new_current_week())
        authed_page.goto(f"{seeded_server}/whats-new")
        authed_page.wait_for_load_state("networkidle")

        authed_page.locator("[data-testid='whats-new-sort-release']").first.click()
        wait_for_htmx(authed_page)

        assert "sort=-release" in authed_page.url
        assert _visible_release_titles(authed_page)[:2] == [
            "Omega Patrol #1",
            "Midnight Flight #1",
        ]
        assert authed_page.locator("#whats-new-sort-input").input_value() == "-release"

        authed_page.locator("[data-testid='whats-new-sort-release']").first.click()
        wait_for_htmx(authed_page)

        assert "sort=release" in authed_page.url
        assert _visible_release_titles(authed_page)[:2] == [
            "Atlas Deluxe #1",
            "Budget Hero #1",
        ]
        assert authed_page.locator("#whats-new-sort-input").input_value() == "release"

        authed_page.locator("[data-testid='whats-new-sort-price']").first.click()
        wait_for_htmx(authed_page)

        assert "sort=price" in authed_page.url
        assert _visible_release_titles(authed_page)[0] == "Budget Hero #1"
        assert authed_page.locator("#whats-new-sort-input").input_value() == "price"

        authed_page.locator("[data-testid='whats-new-sort-publisher']").first.click()
        wait_for_htmx(authed_page)

        assert "sort=publisher" in authed_page.url
        assert _visible_release_titles(authed_page)[:2] == [
            "Midnight Flight #1",
            "Omega Patrol #1",
        ]
        assert authed_page.locator("#whats-new-sort-input").input_value() == "publisher"
