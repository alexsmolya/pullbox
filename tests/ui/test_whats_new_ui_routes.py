"""Route-contract tests for the What's New page shell."""

from __future__ import annotations

import os
import sys
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from pullbox.models.whats_new import WhatsNewCacheKind, WhatsNewReleaseCache

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

pytest_plugins = ["conftest_security"]

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-whats-new-ui")

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _cache_status_markup(response_text: str) -> str:
    start = response_text.index('data-testid="whats-new-cache-status"')
    end = response_text.index("</span>", start)
    return response_text[start:end]


@pytest.mark.asyncio
async def test_whats_new_page_requires_authentication(
    unauthenticated_client,
) -> None:  # type: ignore[no-untyped-def]
    response = await unauthenticated_client.get(
        "/whats-new",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/setup"


@pytest.mark.asyncio
async def test_whats_new_page_renders_empty_shell(
    authenticated_client,
) -> None:  # type: ignore[no-untyped-def]
    response = await authenticated_client.get("/whats-new")

    assert response.status_code == 200
    assert 'data-testid="whats-new-page"' in response.text
    assert 'data-testid="whats-new-header"' in response.text
    assert 'data-testid="whats-new-toolbar"' in response.text
    assert 'data-testid="whats-new-toolbar-frame"' in response.text
    assert 'data-testid="whats-new-results"' in response.text
    assert 'data-testid="whats-new-results-body"' in response.text
    assert 'data-testid="whats-new-gauges"' not in response.text
    assert 'data-testid="whats-new-gauge-this-week"' not in response.text
    assert 'data-testid="whats-new-gauge-coming-soon"' not in response.text
    assert "whats-new-title-block" in response.text
    assert 'data-testid="whats-new-search-field"' in response.text
    assert 'data-search-field-contract="baseline-v2"' in response.text
    assert 'data-search-field-mode="remote"' in response.text
    assert 'id="whats-new-toolbar-form"' in response.text
    assert 'hx-target="#whats-new-results-body"' in response.text
    assert "hx-sync=" in response.text
    assert "#whats-new-results-body:replace" in response.text
    assert 'hx-select="#whats-new-results-body"' not in response.text
    toolbar_start = response.text.index('id="whats-new-toolbar-form"')
    toolbar_end = response.text.index("</form>", toolbar_start)
    toolbar_markup = response.text[toolbar_start:toolbar_end]
    assert 'hx-select-oob="#page-footer-dock"' not in toolbar_markup
    assert 'data-testid="whats-new-publisher-select"' in response.text
    assert 'data-testid="whats-new-sort-select"' not in response.text
    assert "data-whats-new-sort-input" in response.text
    assert 'data-testid="whats-new-per-page-select"' in response.text
    assert 'data-testid="whats-new-view-toggle"' in response.text
    assert 'data-testid="whats-new-pagination"' in response.text
    assert 'data-testid="whats-new-this-week-tab"' in response.text
    assert 'data-testid="whats-new-coming-soon-tab"' in response.text
    assert 'aria-current="page"' in response.text
    assert "x-bind:class=\"{ 'is-active': activeWindow === 'current' }\"" in response.text
    assert "x-bind:class=\"{ 'is-active': activeWindow === 'upcoming' }\"" in response.text
    assert 'data-testid="whats-new-empty-state"' in response.text
    assert "No release data has been cached yet." in response.text


@pytest.mark.asyncio
async def test_whats_new_page_renders_latest_cached_current_week(
    authenticated_client,
    sec_db: async_sessionmaker[AsyncSession],
) -> None:
    fetched_at = datetime.now(UTC)
    async with sec_db() as session:
        session.add(
            WhatsNewReleaseCache(
                cache_key="current-week:2026-03-11",
                cache_kind=WhatsNewCacheKind.CURRENT_WEEK,
                store_date=date(2026, 3, 11),
                payload={
                    "store_date": "2026-03-11",
                    "count": 1,
                    "last_updated": "2026-03-10T12:15:00+00:00",
                    "issues": [_issue_summary()],
                },
                fetched_at=fetched_at,
                last_successful_refresh_at=fetched_at,
            )
        )
        await session.commit()

    response = await authenticated_client.get("/whats-new")

    assert response.status_code == 200
    assert 'data-testid="whats-new-cache-status"' in response.text
    cache_status_markup = _cache_status_markup(response.text)
    assert "pill-success" in cache_status_markup
    assert "whats-new-cache-badge-success" in cache_status_markup
    assert "pill-error" not in cache_status_markup
    assert "whats-new-cache-badge-error" not in cache_status_markup
    assert "Fresh" in response.text
    assert 'data-testid="whats-new-refresh-now"' not in response.text
    assert "Absolute Flash #1" in response.text
    assert "No release data has been cached yet." not in response.text


@pytest.mark.asyncio
async def test_whats_new_page_renders_current_week_release_table(
    authenticated_client,
    sec_db: async_sessionmaker[AsyncSession],
) -> None:
    fetched_at = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)
    async with sec_db() as session:
        session.add(
            WhatsNewReleaseCache(
                cache_key="current-week:2026-03-11",
                cache_kind=WhatsNewCacheKind.CURRENT_WEEK,
                store_date=date(2026, 3, 11),
                payload={
                    "store_date": "2026-03-11",
                    "count": 1,
                    "last_updated": "2026-03-10T12:15:00+00:00",
                    "issues": [_issue_summary()],
                },
                fetched_at=fetched_at,
                last_successful_refresh_at=fetched_at,
            )
        )
        await session.commit()

    response = await authenticated_client.get("/whats-new")

    assert response.status_code == 200
    assert 'data-testid="whats-new-this-week-panel"' in response.text
    assert 'data-testid="whats-new-current-releases"' in response.text
    assert 'data-testid="whats-new-current-release-table"' in response.text
    assert 'data-testid="whats-new-current-compact-release-table"' not in response.text
    assert 'class="series-mission-control-table-wrap"' in response.text
    assert "whats-new-release-table-adaptive" in response.text
    assert "rounded-lg border border-pb-border bg-pb-surface-2 p-4" not in response.text
    assert 'class="downloads-sort-btn"' in response.text
    assert 'data-testid="whats-new-release-row"' in response.text
    assert 'data-testid="whats-new-compact-release-row"' not in response.text
    assert 'src="https://cdn.example.com/1514020.jpg"' in response.text
    assert 'alt="Absolute Flash #1 Cover A cover"' in response.text
    assert "Absolute Flash #1 Cover A" in response.text
    assert "Absolute Flash" in response.text
    assert "DC Comics" in response.text
    assert "In Store" in response.text
    assert "Mar 11" in response.text
    assert "Rating" in response.text
    assert 'data-sort-rating="4.3"' in response.text
    assert "4.3" in response.text
    assert "$4.99" in response.text
    assert "3,100" in response.text
    assert 'data-testid="whats-new-sort-release"' in response.text
    assert 'hx-get="/whats-new?sort=-release"' in response.text
    assert 'hx-sync="#whats-new-results-body:replace"' in response.text
    assert 'hx-sync="&quot;#whats-new-results-body:replace&quot;"' not in response.text
    assert 'hx-sync="&#34;#whats-new-results-body:replace&#34;"' not in response.text


@pytest.mark.asyncio
async def test_whats_new_page_filters_and_paginates_current_week_releases(
    authenticated_client,
    sec_db: async_sessionmaker[AsyncSession],
) -> None:
    fetched_at = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)
    first_match = _issue_summary()
    first_match["locg_issue_id"] = 1515001
    first_match["title"] = "Batman #1"
    first_match["display_title"] = "Batman #1 Cover A"
    first_match["series"] = {
        "title": "Batman",
        "locg_series_id": 190001,
        "locg_url": "https://leagueofcomicgeeks.com/comics/series/190001/batman",
        "start_year": 2026,
        "volume": "2026",
    }
    second_match = _issue_summary()
    second_match["locg_issue_id"] = 1515002
    second_match["title"] = "Batman #2"
    second_match["display_title"] = "Batman #2 Cover A"
    second_match["issue_number"] = "2"
    second_match["series"] = first_match["series"]
    filtered_out = _issue_summary()
    filtered_out["locg_issue_id"] = 1515003
    filtered_out["title"] = "Spider-Man #1"
    filtered_out["display_title"] = "Spider-Man #1 Cover A"
    filtered_out["publisher"] = {
        "name": "Marvel Comics",
        "locg_publisher_id": 502,
        "excluded": False,
        "excluded_reason": None,
    }
    async with sec_db() as session:
        session.add(
            WhatsNewReleaseCache(
                cache_key="current-week:2026-03-11",
                cache_kind=WhatsNewCacheKind.CURRENT_WEEK,
                store_date=date(2026, 3, 11),
                payload={
                    "store_date": "2026-03-11",
                    "count": 3,
                    "last_updated": "2026-03-10T12:15:00+00:00",
                    "issues": [first_match, second_match, filtered_out],
                },
                fetched_at=fetched_at,
                last_successful_refresh_at=fetched_at,
            )
        )
        await session.commit()

    response = await authenticated_client.get(
        "/whats-new",
        params={
            "q": "batman",
            "publisher": "DC Comics",
            "sort": "issue",
            "per_page": "1",
            "page": "2",
        },
    )

    assert response.status_code == 200
    assert 'data-testid="whats-new-pagination"' in response.text
    assert 'data-testid="page-dock-pagination"' in response.text
    assert "Batman #2 Cover A" in response.text
    assert "Batman #1 Cover A" not in response.text
    assert "Spider-Man #1 Cover A" not in response.text
    assert "publisher=DC+Comics" in response.text


@pytest.mark.asyncio
async def test_whats_new_htmx_pagination_returns_results_bundle_and_footer_dock(
    authenticated_client,
    sec_db: async_sessionmaker[AsyncSession],
) -> None:
    fetched_at = datetime.now(UTC)
    first_match = _issue_summary()
    first_match["locg_issue_id"] = 1515001
    first_match["title"] = "Batman #1"
    first_match["display_title"] = "Batman #1 Cover A"
    first_match["series"] = {
        "title": "Batman",
        "locg_series_id": 190001,
        "locg_url": "https://leagueofcomicgeeks.com/comics/series/190001/batman",
        "start_year": 2026,
        "volume": "2026",
    }
    second_match = _issue_summary()
    second_match["locg_issue_id"] = 1515002
    second_match["title"] = "Batman #2"
    second_match["display_title"] = "Batman #2 Cover A"
    second_match["issue_number"] = "2"
    second_match["series"] = first_match["series"]
    async with sec_db() as session:
        session.add(
            WhatsNewReleaseCache(
                cache_key="current-week:2026-03-11",
                cache_kind=WhatsNewCacheKind.CURRENT_WEEK,
                store_date=date(2026, 3, 11),
                payload={
                    "store_date": "2026-03-11",
                    "count": 2,
                    "last_updated": "2026-03-10T12:15:00+00:00",
                    "issues": [first_match, second_match],
                },
                fetched_at=fetched_at,
                last_successful_refresh_at=fetched_at,
            )
        )
        await session.commit()

    response = await authenticated_client.get(
        "/whats-new",
        params={"q": "batman", "sort": "issue", "per_page": "1", "page": "2"},
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    assert 'data-testid="whats-new-page"' not in response.text
    assert 'id="page-footer-dock" hx-swap-oob="innerHTML"' in response.text
    assert 'id="whats-new-sort-input"' in response.text
    assert 'id="whats-new-results-body"' in response.text
    assert 'data-testid="page-dock-pagination"' in response.text
    assert 'id="whats-new-publisher-field"' in response.text
    assert 'hx-swap-oob="outerHTML"' in response.text
    assert 'data-testid="series-pagination-prev"' in response.text
    assert 'hx-target="#whats-new-results-body"' in response.text
    assert "hx-sync=" in response.text
    assert "#whats-new-results-body:replace" in response.text
    assert "&quot;#whats-new-results-body:replace&quot;" not in response.text
    assert "&#34;#whats-new-results-body:replace&#34;" not in response.text
    assert "hx-select=" not in response.text
    assert "hx-select-oob=" not in response.text
    assert "Batman #2 Cover A" in response.text
    assert "Batman #1 Cover A" not in response.text


@pytest.mark.asyncio
async def test_whats_new_page_sorts_full_result_set_by_price_before_paginating(
    authenticated_client,
    sec_db: async_sessionmaker[AsyncSession],
) -> None:
    fetched_at = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)
    expensive = _issue_summary()
    expensive["locg_issue_id"] = 1516001
    expensive["display_title"] = "Expensive Book #1"
    expensive["title"] = "Expensive Book #1"
    expensive["price"] = 5.99
    expensive["issue_number"] = "1"
    expensive["series"] = {
        "title": "Expensive Book",
        "locg_series_id": 191001,
        "locg_url": "https://leagueofcomicgeeks.com/comics/series/191001/expensive-book",
        "start_year": 2026,
        "volume": "2026",
    }
    medium = _issue_summary()
    medium["locg_issue_id"] = 1516002
    medium["display_title"] = "Medium Book #1"
    medium["title"] = "Medium Book #1"
    medium["price"] = 3.99
    medium["issue_number"] = "1"
    medium["series"] = {
        "title": "Medium Book",
        "locg_series_id": 191002,
        "locg_url": "https://leagueofcomicgeeks.com/comics/series/191002/medium-book",
        "start_year": 2026,
        "volume": "2026",
    }
    cheap = _issue_summary()
    cheap["locg_issue_id"] = 1516003
    cheap["display_title"] = "Cheap Book #1"
    cheap["title"] = "Cheap Book #1"
    cheap["price"] = 1.99
    cheap["issue_number"] = "1"
    cheap["series"] = {
        "title": "Cheap Book",
        "locg_series_id": 191003,
        "locg_url": "https://leagueofcomicgeeks.com/comics/series/191003/cheap-book",
        "start_year": 2026,
        "volume": "2026",
    }
    async with sec_db() as session:
        session.add(
            WhatsNewReleaseCache(
                cache_key="current-week:2026-03-11",
                cache_kind=WhatsNewCacheKind.CURRENT_WEEK,
                store_date=date(2026, 3, 11),
                payload={
                    "store_date": "2026-03-11",
                    "count": 3,
                    "last_updated": "2026-03-10T12:15:00+00:00",
                    "issues": [expensive, medium, cheap],
                },
                fetched_at=fetched_at,
                last_successful_refresh_at=fetched_at,
            )
        )
        await session.commit()

    response = await authenticated_client.get(
        "/whats-new",
        params={"sort": "price", "per_page": "1", "page": "2"},
    )

    assert response.status_code == 200
    assert "Medium Book #1" in response.text
    assert "Cheap Book #1" not in response.text
    assert "Expensive Book #1" not in response.text


@pytest.mark.asyncio
async def test_whats_new_page_uses_release_title_as_secondary_sort_tiebreak(
    authenticated_client,
    sec_db: async_sessionmaker[AsyncSession],
) -> None:
    fetched_at = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)
    zebra = _issue_summary()
    zebra["locg_issue_id"] = 1516101
    zebra["display_title"] = "Zebra Tales #1"
    zebra["title"] = "Zebra Tales #1"
    zebra["price"] = 3.99
    zebra["series"] = {
        "title": "Zebra Tales",
        "locg_series_id": 191101,
        "locg_url": "https://leagueofcomicgeeks.com/comics/series/191101/zebra-tales",
        "start_year": 2026,
        "volume": "2026",
    }
    alpha = _issue_summary()
    alpha["locg_issue_id"] = 1516102
    alpha["display_title"] = "Alpha Flight #1"
    alpha["title"] = "Alpha Flight #1"
    alpha["price"] = 3.99
    alpha["series"] = {
        "title": "Alpha Flight",
        "locg_series_id": 191102,
        "locg_url": "https://leagueofcomicgeeks.com/comics/series/191102/alpha-flight",
        "start_year": 2026,
        "volume": "2026",
    }
    async with sec_db() as session:
        session.add(
            WhatsNewReleaseCache(
                cache_key="current-week:2026-03-11",
                cache_kind=WhatsNewCacheKind.CURRENT_WEEK,
                store_date=date(2026, 3, 11),
                payload={
                    "store_date": "2026-03-11",
                    "count": 2,
                    "last_updated": "2026-03-10T12:15:00+00:00",
                    "issues": [zebra, alpha],
                },
                fetched_at=fetched_at,
                last_successful_refresh_at=fetched_at,
            )
        )
        await session.commit()

    response = await authenticated_client.get(
        "/whats-new",
        params={"sort": "price", "per_page": "25"},
    )

    assert response.status_code == 200
    assert response.text.index("Alpha Flight #1") < response.text.index("Zebra Tales #1")


@pytest.mark.asyncio
async def test_whats_new_page_sorts_issue_numbers_numerically_and_displays_empty_as_dash(
    authenticated_client,
    sec_db: async_sessionmaker[AsyncSession],
) -> None:
    fetched_at = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)
    issue_ten = _issue_summary()
    issue_ten["locg_issue_id"] = 1516201
    issue_ten["display_title"] = "Issue Ten"
    issue_ten["title"] = "Issue Ten"
    issue_ten["issue_number"] = "10"
    issue_ten["series"] = {
        "title": "Issue Ten Series",
        "locg_series_id": 191201,
        "locg_url": "https://leagueofcomicgeeks.com/comics/series/191201/issue-ten-series",
        "start_year": 2026,
        "volume": "2026",
    }
    issue_two = _issue_summary()
    issue_two["locg_issue_id"] = 1516202
    issue_two["display_title"] = "Issue Two"
    issue_two["title"] = "Issue Two"
    issue_two["issue_number"] = "2"
    issue_two["series"] = {
        "title": "Issue Two Series",
        "locg_series_id": 191202,
        "locg_url": "https://leagueofcomicgeeks.com/comics/series/191202/issue-two-series",
        "start_year": 2026,
        "volume": "2026",
    }
    collection = _issue_summary()
    collection["locg_issue_id"] = 1516203
    collection["display_title"] = "Collected Edition"
    collection["title"] = "Collected Edition"
    collection["issue_number"] = None
    collection["series"] = {
        "title": "Collected Edition Series",
        "locg_series_id": 191203,
        "locg_url": "https://leagueofcomicgeeks.com/comics/series/191203/collected-edition-series",
        "start_year": 2026,
        "volume": "2026",
    }
    async with sec_db() as session:
        session.add(
            WhatsNewReleaseCache(
                cache_key="current-week:2026-03-11",
                cache_kind=WhatsNewCacheKind.CURRENT_WEEK,
                store_date=date(2026, 3, 11),
                payload={
                    "store_date": "2026-03-11",
                    "count": 3,
                    "last_updated": "2026-03-10T12:15:00+00:00",
                    "issues": [issue_ten, collection, issue_two],
                },
                fetched_at=fetched_at,
                last_successful_refresh_at=fetched_at,
            )
        )
        await session.commit()

    response = await authenticated_client.get(
        "/whats-new",
        params={"sort": "issue", "per_page": "25"},
    )

    assert response.status_code == 200
    assert response.text.index("Issue Two") < response.text.index("Issue Ten")
    assert response.text.index("Issue Ten") < response.text.index("Collected Edition")
    normalized_markup = response.text.replace(" ", "").replace("\n", "")
    assert ">-</td>" in normalized_markup


@pytest.mark.asyncio
async def test_whats_new_page_switches_to_upcoming_window_with_footer_state(
    authenticated_client,
    sec_db: async_sessionmaker[AsyncSession],
) -> None:
    fetched_at = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)
    async with sec_db() as session:
        session.add(
            WhatsNewReleaseCache(
                cache_key="upcoming:all",
                cache_kind=WhatsNewCacheKind.UPCOMING,
                payload={
                    "weeks": [
                        {
                            "store_date": "2026-03-25",
                            "count": 1,
                            "issues": [_issue_summary()],
                        }
                    ],
                    "lookahead_weeks": 2,
                },
                fetched_at=fetched_at,
                last_successful_refresh_at=fetched_at,
            )
        )
        await session.commit()

    response = await authenticated_client.get("/whats-new", params={"window": "upcoming"})

    assert response.status_code == 200
    assert 'data-testid="whats-new-coming-soon-panel"' in response.text
    assert 'data-testid="whats-new-this-week-panel"' not in response.text
    assert 'data-testid="page-dock-status"' in response.text
    assert "coming soon" in response.text


@pytest.mark.asyncio
async def test_whats_new_page_selects_one_upcoming_release_week(
    authenticated_client,
    sec_db: async_sessionmaker[AsyncSession],
) -> None:
    fetched_at = datetime.now(UTC)
    first_week_issue = _issue_summary()
    first_week_issue["locg_issue_id"] = 1516001
    first_week_issue["title"] = "First Week Book #1"
    first_week_issue["display_title"] = "First Week Book #1"
    first_week_issue["store_date"] = "2026-03-25"
    first_week_issue["series"] = {
        "title": "First Week Book",
        "locg_series_id": 191001,
        "locg_url": "https://leagueofcomicgeeks.com/comics/series/191001/first-week-book",
        "start_year": 2026,
        "volume": "2026",
    }
    second_week_issue = _issue_summary()
    second_week_issue["locg_issue_id"] = 1517001
    second_week_issue["title"] = "Second Week Book #1"
    second_week_issue["display_title"] = "Second Week Book #1"
    second_week_issue["store_date"] = "2026-04-01"
    second_week_issue["series"] = {
        "title": "Second Week Book",
        "locg_series_id": 191002,
        "locg_url": "https://leagueofcomicgeeks.com/comics/series/191002/second-week-book",
        "start_year": 2026,
        "volume": "2026",
    }
    async with sec_db() as session:
        session.add(
            WhatsNewReleaseCache(
                cache_key="upcoming:all",
                cache_kind=WhatsNewCacheKind.UPCOMING,
                payload={
                    "weeks": [
                        {
                            "store_date": "2026-03-25",
                            "count": 1,
                            "issues": [first_week_issue],
                        },
                        {
                            "store_date": "2026-04-01",
                            "count": 1,
                            "issues": [second_week_issue],
                        },
                    ],
                    "lookahead_weeks": 2,
                },
                fetched_at=fetched_at,
                last_successful_refresh_at=fetched_at,
            )
        )
        await session.commit()

    response = await authenticated_client.get(
        "/whats-new",
        params={"window": "upcoming", "release_week": "2026-04-01"},
    )

    assert response.status_code == 200
    assert 'data-testid="whats-new-week-nav"' in response.text
    assert 'data-testid="whats-new-week-select"' in response.text
    assert 'data-dropdown-select-contract="v1"' in response.text
    assert 'data-testid="whats-new-week-trigger"' in response.text
    assert 'data-testid="whats-new-week-panel"' in response.text
    assert 'data-testid="whats-new-week-input"' in response.text
    assert "form=whats-new-toolbar-form" in response.text
    assert 'data-dropdown-value="2026-04-01"' in response.text
    assert 'data-testid="whats-new-week-prev"' in response.text
    assert 'data-testid="whats-new-week-next-disabled"' in response.text
    assert "Week 2 of 2" in response.text
    assert "Second Week Book #1" in response.text
    assert "First Week Book #1" not in response.text
    assert "release_week=2026-03-25" in response.text


@pytest.mark.asyncio
async def test_whats_new_publisher_options_follow_active_window_and_release_week(
    authenticated_client,
    sec_db: async_sessionmaker[AsyncSession],
) -> None:
    fetched_at = datetime.now(UTC)
    current_issue = _issue_summary()
    current_issue["title"] = "Current Week Book #1"
    current_issue["display_title"] = "Current Week Book #1"
    current_issue["publisher"] = {
        "name": "Marvel Comics",
        "locg_publisher_id": 502,
        "excluded": False,
        "excluded_reason": None,
    }
    first_week_issue = _issue_summary()
    first_week_issue["locg_issue_id"] = 1516001
    first_week_issue["title"] = "First Upcoming Book #1"
    first_week_issue["display_title"] = "First Upcoming Book #1"
    first_week_issue["store_date"] = "2026-03-25"
    first_week_issue["publisher"] = {
        "name": "DC Comics",
        "locg_publisher_id": 501,
        "excluded": False,
        "excluded_reason": None,
    }
    second_week_issue = _issue_summary()
    second_week_issue["locg_issue_id"] = 1517001
    second_week_issue["title"] = "Second Upcoming Book #1"
    second_week_issue["display_title"] = "Second Upcoming Book #1"
    second_week_issue["store_date"] = "2026-04-01"
    second_week_issue["publisher"] = {
        "name": "Image Comics",
        "locg_publisher_id": 503,
        "excluded": False,
        "excluded_reason": None,
    }
    async with sec_db() as session:
        session.add_all(
            [
                WhatsNewReleaseCache(
                    cache_key="current-week:2026-03-11",
                    cache_kind=WhatsNewCacheKind.CURRENT_WEEK,
                    store_date=date(2026, 3, 11),
                    payload={
                        "store_date": "2026-03-11",
                        "count": 1,
                        "last_updated": "2026-03-10T12:15:00+00:00",
                        "issues": [current_issue],
                    },
                    fetched_at=fetched_at,
                    last_successful_refresh_at=fetched_at,
                ),
                WhatsNewReleaseCache(
                    cache_key="upcoming:all",
                    cache_kind=WhatsNewCacheKind.UPCOMING,
                    payload={
                        "weeks": [
                            {
                                "store_date": "2026-03-25",
                                "count": 1,
                                "issues": [first_week_issue],
                            },
                            {
                                "store_date": "2026-04-01",
                                "count": 1,
                                "issues": [second_week_issue],
                            },
                        ],
                        "lookahead_weeks": 2,
                    },
                    fetched_at=fetched_at,
                    last_successful_refresh_at=fetched_at,
                ),
            ]
        )
        await session.commit()

    current_response = await authenticated_client.get("/whats-new")
    upcoming_response = await authenticated_client.get(
        "/whats-new",
        params={"window": "upcoming", "release_week": "2026-04-01"},
    )

    assert current_response.status_code == 200
    assert "Marvel Comics" in current_response.text
    assert "DC Comics" not in current_response.text
    assert "Image Comics" not in current_response.text
    assert upcoming_response.status_code == 200
    assert "Image Comics" in upcoming_response.text
    assert "Marvel Comics" not in upcoming_response.text
    assert "DC Comics" not in upcoming_response.text


@pytest.mark.asyncio
async def test_whats_new_invalid_publisher_filter_resets_for_selected_week(
    authenticated_client,
    sec_db: async_sessionmaker[AsyncSession],
) -> None:
    fetched_at = datetime.now(UTC)
    first_week_issue = _issue_summary()
    first_week_issue["locg_issue_id"] = 1516001
    first_week_issue["title"] = "First Upcoming Book #1"
    first_week_issue["display_title"] = "First Upcoming Book #1"
    first_week_issue["store_date"] = "2026-03-25"
    first_week_issue["publisher"] = {
        "name": "DC Comics",
        "locg_publisher_id": 501,
        "excluded": False,
        "excluded_reason": None,
    }
    second_week_issue = _issue_summary()
    second_week_issue["locg_issue_id"] = 1517001
    second_week_issue["title"] = "Second Upcoming Book #1"
    second_week_issue["display_title"] = "Second Upcoming Book #1"
    second_week_issue["store_date"] = "2026-04-01"
    second_week_issue["publisher"] = {
        "name": "Image Comics",
        "locg_publisher_id": 503,
        "excluded": False,
        "excluded_reason": None,
    }
    async with sec_db() as session:
        session.add(
            WhatsNewReleaseCache(
                cache_key="upcoming:all",
                cache_kind=WhatsNewCacheKind.UPCOMING,
                payload={
                    "weeks": [
                        {
                            "store_date": "2026-03-25",
                            "count": 1,
                            "issues": [first_week_issue],
                        },
                        {
                            "store_date": "2026-04-01",
                            "count": 1,
                            "issues": [second_week_issue],
                        },
                    ],
                    "lookahead_weeks": 2,
                },
                fetched_at=fetched_at,
                last_successful_refresh_at=fetched_at,
            )
        )
        await session.commit()

    response = await authenticated_client.get(
        "/whats-new",
        params={
            "window": "upcoming",
            "release_week": "2026-04-01",
            "publisher": "DC Comics",
        },
    )

    assert response.status_code == 200
    assert "Second Upcoming Book #1" in response.text
    assert "No upcoming releases match the current filters." not in response.text
    assert "Image Comics" in response.text
    assert "DC Comics" not in response.text
    assert 'data-testid="whats-new-publisher-select"' in response.text
    assert 'data-dropdown-value=""' in response.text


@pytest.mark.asyncio
async def test_whats_new_page_keeps_current_week_to_matching_store_date(
    authenticated_client,
    sec_db: async_sessionmaker[AsyncSession],
) -> None:
    fetched_at = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)
    current_issue = _issue_summary()
    future_issue = _issue_summary()
    future_issue["locg_issue_id"] = 1515001
    future_issue["title"] = "Future Book #1"
    future_issue["display_title"] = "Future Book #1"
    future_issue["store_date"] = "2026-03-18"
    future_issue["series"] = {
        "title": "Future Book",
        "locg_series_id": 190001,
        "locg_url": "https://leagueofcomicgeeks.com/comics/series/190001/future-book",
        "start_year": 2026,
        "volume": "2026",
    }
    async with sec_db() as session:
        session.add(
            WhatsNewReleaseCache(
                cache_key="current-week:2026-03-11",
                cache_kind=WhatsNewCacheKind.CURRENT_WEEK,
                store_date=date(2026, 3, 11),
                payload={
                    "store_date": "2026-03-11",
                    "count": 2,
                    "last_updated": "2026-03-10T12:15:00+00:00",
                    "issues": [current_issue, future_issue],
                },
                fetched_at=fetched_at,
                last_successful_refresh_at=fetched_at,
            )
        )
        await session.commit()

    response = await authenticated_client.get("/whats-new")

    assert response.status_code == 200
    assert "Absolute Flash #1 Cover A" in response.text
    assert "Future Book #1" not in response.text
    assert 'data-testid="page-dock-status"' in response.text


@pytest.mark.asyncio
async def test_whats_new_page_groups_variant_rows_by_logical_issue(
    authenticated_client,
    sec_db: async_sessionmaker[AsyncSession],
) -> None:
    fetched_at = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)
    cover_a = _issue_summary()
    cover_a["variant_count"] = 0
    cover_b = _issue_summary()
    cover_b["locg_issue_id"] = 1514021
    cover_b["display_title"] = "Absolute Flash #1 Cover B Variant"
    cover_b["title"] = "Absolute Flash #1 Cover B Variant"
    cover_b["cover_url"] = "https://cdn.example.com/1514021.jpg"
    cover_b["variant_count"] = 0
    async with sec_db() as session:
        session.add(
            WhatsNewReleaseCache(
                cache_key="current-week:2026-03-11",
                cache_kind=WhatsNewCacheKind.CURRENT_WEEK,
                store_date=date(2026, 3, 11),
                payload={
                    "store_date": "2026-03-11",
                    "count": 2,
                    "last_updated": "2026-03-10T12:15:00+00:00",
                    "issues": [cover_a, cover_b],
                },
                fetched_at=fetched_at,
                last_successful_refresh_at=fetched_at,
            )
        )
        await session.commit()

    response = await authenticated_client.get("/whats-new")

    assert response.status_code == 200
    assert response.text.count('data-testid="whats-new-release-row"') == 1
    assert "Absolute Flash #1 Cover B Variant" not in response.text
    assert ">1</span>" in response.text


@pytest.mark.asyncio
async def test_whats_new_page_trusts_upstream_publisher_filtering(
    authenticated_client,
    sec_db: async_sessionmaker[AsyncSession],
) -> None:
    fetched_at = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)
    supported = _issue_summary()
    upstream_release = _issue_summary()
    upstream_release["locg_issue_id"] = 1514999
    upstream_release["title"] = "Upstream Provided Release #1"
    upstream_release["display_title"] = "Upstream Provided Release #1"
    upstream_release["publisher"] = {
        "name": "Kodansha Comics",
        "locg_publisher_id": 9001,
        "excluded": False,
        "excluded_reason": None,
    }
    upstream_release["series"] = {
        "title": "Upstream Provided Release",
        "locg_series_id": 9002,
        "locg_url": "https://leagueofcomicgeeks.com/comics/series/9002/upstream-release",
        "start_year": 2026,
        "volume": "2026",
    }
    async with sec_db() as session:
        session.add(
            WhatsNewReleaseCache(
                cache_key="current-week:2026-03-11",
                cache_kind=WhatsNewCacheKind.CURRENT_WEEK,
                store_date=date(2026, 3, 11),
                payload={
                    "store_date": "2026-03-11",
                    "count": 2,
                    "last_updated": "2026-03-10T12:15:00+00:00",
                    "issues": [supported, upstream_release],
                },
                fetched_at=fetched_at,
                last_successful_refresh_at=fetched_at,
            )
        )
        await session.commit()

    response = await authenticated_client.get("/whats-new")

    assert response.status_code == 200
    assert "Absolute Flash #1 Cover A" in response.text
    assert "Upstream Provided Release #1" in response.text
    assert "Kodansha Comics" in response.text
    assert "filtered" not in response.text.lower()
    assert "Grouped" not in response.text


@pytest.mark.asyncio
async def test_whats_new_page_renders_release_cards_with_string_prices(
    authenticated_client,
    sec_db: async_sessionmaker[AsyncSession],
) -> None:
    fetched_at = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)
    issue = _issue_summary()
    issue["price"] = "4.99"
    async with sec_db() as session:
        session.add(
            WhatsNewReleaseCache(
                cache_key="current-week:2026-03-11",
                cache_kind=WhatsNewCacheKind.CURRENT_WEEK,
                store_date=date(2026, 3, 11),
                payload={
                    "store_date": "2026-03-11",
                    "count": 1,
                    "last_updated": "2026-03-10T12:15:00+00:00",
                    "issues": [issue],
                },
                fetched_at=fetched_at,
                last_successful_refresh_at=fetched_at,
            )
        )
        await session.commit()

    response = await authenticated_client.get("/whats-new")

    assert response.status_code == 200
    assert "Absolute Flash #1 Cover A" in response.text
    assert "$4.99" in response.text


@pytest.mark.asyncio
async def test_whats_new_page_warns_when_cached_data_is_stale(
    authenticated_client,
    sec_db: async_sessionmaker[AsyncSession],
) -> None:
    fetched_at = datetime.now(UTC) - timedelta(hours=7)
    async with sec_db() as session:
        session.add(
            WhatsNewReleaseCache(
                cache_key="current-week:2026-03-11",
                cache_kind=WhatsNewCacheKind.CURRENT_WEEK,
                store_date=date(2026, 3, 11),
                payload={
                    "store_date": "2026-03-11",
                    "count": 1,
                    "last_updated": "2026-03-10T12:15:00+00:00",
                    "issues": [_issue_summary()],
                },
                fetched_at=fetched_at,
                last_successful_refresh_at=fetched_at,
            )
        )
        await session.commit()

    response = await authenticated_client.get("/whats-new")

    assert response.status_code == 200
    assert 'data-testid="whats-new-stale-banner"' in response.text
    cache_status_markup = _cache_status_markup(response.text)
    assert "pill-error" in cache_status_markup
    assert "whats-new-cache-badge-error" in cache_status_markup
    assert "pill-success" not in cache_status_markup
    assert "whats-new-cache-badge-success" not in cache_status_markup
    assert "Stale" in response.text
    assert "Showing cached release data while Pullbox waits for the next refresh." in response.text
    assert 'data-testid="whats-new-refresh-now"' in response.text
    assert "whatsNewRefreshControl(" in response.text
    assert "currentStale: true" in response.text
    assert "upcomingStale: false" in response.text
    refresh_marker = response.text.index('data-testid="whats-new-refresh-now"')
    refresh_start = response.text.rfind("<button", 0, refresh_marker)
    refresh_end = response.text.index("</button>", refresh_marker)
    refresh_markup = response.text[refresh_start:refresh_end]
    assert 'class="btn-primary gap-2 shrink-0"' in refresh_markup
    assert 'class="h-4 w-4"' in refresh_markup
    assert refresh_markup.index("<svg") < refresh_markup.index("<span")
    assert "Refresh now" in refresh_markup
    assert "Absolute Flash #1" in response.text


@pytest.mark.asyncio
async def test_whats_new_page_renders_cached_upcoming_context(
    authenticated_client,
    sec_db: async_sessionmaker[AsyncSession],
) -> None:
    fetched_at = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)
    async with sec_db() as session:
        session.add(
            WhatsNewReleaseCache(
                cache_key="upcoming:all",
                cache_kind=WhatsNewCacheKind.UPCOMING,
                payload={
                    "weeks": [
                        {
                            "store_date": "2026-03-25",
                            "count": 1,
                            "issues": [_issue_summary()],
                        }
                    ],
                    "lookahead_weeks": 2,
                },
                fetched_at=fetched_at,
                last_successful_refresh_at=fetched_at,
            )
        )
        await session.commit()

    response = await authenticated_client.get("/whats-new")

    assert response.status_code == 200
    assert 'data-testid="whats-new-week-nav"' in response.text
    assert "Coming Soon" in response.text


@pytest.mark.asyncio
async def test_whats_new_page_renders_upcoming_release_sections(
    authenticated_client,
    sec_db: async_sessionmaker[AsyncSession],
) -> None:
    fetched_at = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)
    async with sec_db() as session:
        session.add(
            WhatsNewReleaseCache(
                cache_key="upcoming:all",
                cache_kind=WhatsNewCacheKind.UPCOMING,
                payload={
                    "weeks": [
                        {
                            "store_date": "2026-03-25",
                            "count": 1,
                            "issues": [_issue_summary()],
                        }
                    ],
                    "lookahead_weeks": 2,
                },
                fetched_at=fetched_at,
                last_successful_refresh_at=fetched_at,
            )
        )
        await session.commit()

    response = await authenticated_client.get("/whats-new")

    assert response.status_code == 200
    assert 'data-testid="whats-new-coming-soon-panel"' in response.text
    assert 'data-testid="whats-new-upcoming-releases"' in response.text
    assert 'data-testid="whats-new-upcoming-release-table"' in response.text
    assert 'data-testid="whats-new-upcoming-compact-release-table"' not in response.text
    assert "In Store" in response.text
    assert "Mar 25" in response.text
    assert "Absolute Flash #1 Cover A" in response.text


def _issue_summary() -> dict[str, object]:
    return {
        "locg_issue_id": 1514020,
        "locg_series_id": 180901,
        "locg_url": "https://leagueofcomicgeeks.com/comic/1514020/absolute-flash-1",
        "title": "Absolute Flash #1",
        "display_title": "Absolute Flash #1 Cover A",
        "issue_number": "1",
        "price": 4.99,
        "currency": "USD",
        "store_date": "2026-03-11",
        "cover_url": "https://cdn.example.com/1514020.jpg",
        "variant_count": 9,
        "community_rating": 4.3,
        "community_counts": {
            "pull": 3100,
            "have": 0,
            "read": 0,
            "want": 1400,
            "pick": 260,
        },
        "publisher": {
            "name": "DC Comics",
            "locg_publisher_id": 501,
            "excluded": False,
            "excluded_reason": None,
        },
        "series": {
            "title": "Absolute Flash",
            "locg_series_id": 180901,
            "locg_url": "https://leagueofcomicgeeks.com/comics/series/180901/absolute-flash",
            "start_year": 2026,
            "volume": "2026",
        },
    }
