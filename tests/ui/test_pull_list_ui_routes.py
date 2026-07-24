"""Route-contract tests for the redesigned pull list page."""

from __future__ import annotations

import os
import re
import sys
from html import unescape
from urllib.parse import parse_qs, urlparse

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pullbox.models.issue import Issue, IssueStatus
from pullbox.models.publisher import Publisher
from pullbox.models.series import Series
from pullbox.services.auth_service import SESSION_COOKIE_NAME, AuthService

pytest_plugins = ["conftest_security"]

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-pull-list-ui")


def _csrf_header_for(client) -> dict[str, str]:  # type: ignore[no-untyped-def]
    token = client.cookies.get(SESSION_COOKIE_NAME) or ""
    csrf = AuthService.get_csrf_token_from_session(token) or ""
    return {"X-CSRF-Token": csrf}


async def _seed_pull_list_series(
    factory,
) -> int:
    """Create a monitored series so the route can render table-level tooltip contracts."""
    async with factory() as session:
        publisher = Publisher(name="Extremely Long Publisher Name For Tooltip Coverage")
        session.add(publisher)
        await session.flush()

        series = Series(
            title="An Extremely Long Pull List Series Title That Should Truncate Cleanly",
            sort_title="Extremely Long Pull List Series Title That Should Truncate Cleanly",
            monitored=True,
            year_start=2024,
            publisher_id=publisher.id,
        )
        session.add(series)
        await session.flush()
        series_id = series.id

        session.add_all(
            [
                Issue(series_id=series.id, issue_number=1, status=IssueStatus.OWNED),
                Issue(series_id=series.id, issue_number=2, status=IssueStatus.WANTED),
                Issue(series_id=series.id, issue_number=3, status=IssueStatus.DOWNLOADING),
            ]
        )
        await session.commit()
        return series_id


@pytest.mark.asyncio
class TestPullListRouteContracts:
    """Verify the pull list matches the slimmed shared UI contract."""

    async def test_pull_list_renders_registry_header_table_and_footer_dock(
        self,
        authenticated_client,
    ) -> None:  # type: ignore[no-untyped-def]
        response = await authenticated_client.get("/pull-list")

        assert response.status_code == 200
        assert 'data-testid="pull-list-page"' in response.text
        assert 'data-testid="pull-list-header"' in response.text
        assert 'data-testid="pull-list-title"' in response.text
        assert 'data-testid="pull-list-subtitle"' in response.text
        assert 'data-testid="pull-list-gauges"' in response.text
        assert 'data-testid="pull-list-gauge-series"' in response.text
        assert 'data-testid="pull-list-gauge-wanted"' in response.text
        assert 'data-testid="pull-list-filter-form"' in response.text
        assert 'id="pull-list-sort-input"' in response.text
        assert 'data-testid="pull-list-search-field"' in response.text
        assert 'data-testid="pull-list-search-input"' in response.text
        assert 'data-testid="pull-list-search-clear"' in response.text
        assert 'data-testid="pull-list-search-history-panel"' in response.text
        assert 'data-search-history-key="pullbox.searchHistory.pullList"' in response.text
        assert 'data-search-field-contract="baseline-v2"' in response.text
        assert 'data-search-field-mode="remote"' in response.text
        assert 'data-testid="pull-list-filter-select"' in response.text
        assert 'data-testid="pull-list-per-page-select"' in response.text
        assert 'name="per_page"' in response.text
        assert 'value="25"' in response.text
        assert 'data-dropdown-select-contract="v1"' in response.text
        assert "Paused (Unmonitored)" not in response.text
        assert 'data-testid="pull-list-add-series"' in response.text
        assert 'data-testid="pull-list-table-shell"' in response.text
        assert 'data-testid="pull-list-results-body"' in response.text
        assert 'hx-get="/pull-list"' in response.text
        assert 'hx-target="#pull-list-results-body"' in response.text
        assert 'hx-swap="outerHTML"' in response.text
        assert 'hx-push-url="true"' in response.text
        assert 'hx-trigger="submit"' in response.text
        assert (
            'data-testid="pull-list-table"' in response.text
            or 'data-testid="pull-list-empty"' in response.text
        )
        assert 'data-testid="pull-list-footer-dock"' in response.text
        assert 'data-testid="page-dock-status"' in response.text
        assert "Keep track of what still needs to be found" not in response.text
        assert "What the pull list is for" not in response.text
        assert "Current filter" not in response.text
        assert '<select id="pull-filter"' not in response.text

    async def test_pull_list_per_page_controls_the_global_result_page(
        self,
        authenticated_client,
        sec_db,
    ) -> None:  # type: ignore[no-untyped-def]
        async with sec_db() as session:
            session.add_all(
                [
                    Series(
                        title=f"Pull List Page Size {index}",
                        sort_title=f"pull list page size {index}",
                        monitored=True,
                    )
                    for index in range(3)
                ]
            )
            await session.commit()

        response = await authenticated_client.get("/pull-list?per_page=1&page=2")

        assert response.status_code == 200
        assert response.text.count('data-testid="pull-list-row-') == 1
        assert 'data-testid="pull-list-per-page-select"' in response.text
        assert 'data-dropdown-value="1"' in response.text
        assert 'data-testid="page-dock-pagination"' in response.text
        assert "per_page=1" in response.text

    async def test_pull_list_sort_preserves_the_selected_page_size(
        self,
        authenticated_client,
        sec_db,
    ) -> None:  # type: ignore[no-untyped-def]
        await _seed_pull_list_series(sec_db)

        response = await authenticated_client.get("/pull-list?per_page=50")

        assert response.status_code == 200
        assert 'hx-get="/pull-list?sort=-wanted&amp;per_page=50"' in response.text

    async def test_pull_list_empty_state_stays_inside_table_shell(
        self,
        authenticated_client,
    ) -> None:  # type: ignore[no-untyped-def]
        response = await authenticated_client.get("/pull-list?filter=paused")

        assert response.status_code == 200
        assert 'data-testid="pull-list-table-shell"' in response.text
        assert 'data-testid="pull-list-empty"' in response.text
        assert 'data-testid="pull-list-footer-dock"' in response.text

    async def test_pull_list_hx_request_returns_results_bundle_only(
        self,
        authenticated_client,
    ) -> None:  # type: ignore[no-untyped-def]
        response = await authenticated_client.get(
            "/pull-list?search=Batman",
            headers={"HX-Request": "true"},
        )

        assert response.status_code == 200
        assert 'id="pull-list-sort-input"' in response.text
        assert 'id="page-footer-dock"' in response.text
        assert 'data-testid="pull-list-results-body"' in response.text
        assert 'data-testid="pull-list-page"' not in response.text
        assert 'data-testid="pull-list-filter-form"' not in response.text

    async def test_pull_list_search_query_round_trips_into_shared_search_field(
        self,
        authenticated_client,
    ) -> None:  # type: ignore[no-untyped-def]
        response = await authenticated_client.get("/pull-list?search=Batman")

        assert response.status_code == 200
        assert 'data-testid="pull-list-search-input"' in response.text
        assert 'name="search"' in response.text
        assert 'value="Batman"' in response.text

    async def test_pull_list_rows_use_shared_tooltip_and_action_button_contracts(
        self,
        authenticated_client,
        sec_db,
    ) -> None:  # type: ignore[no-untyped-def]
        await _seed_pull_list_series(sec_db)

        response = await authenticated_client.get("/pull-list")

        assert response.status_code == 200
        assert 'data-testid="pull-list-row-' in response.text
        assert 'data-testid="pull-list-search-' in response.text
        assert 'class="downloads-release-name tooltip-wrap"' in response.text
        assert "data-tooltip-auto" in response.text
        assert "data-tooltip-measure" in response.text
        assert 'class="downloads-action-btn"' in response.text
        assert 'class="series-monitor-badge pull-list-monitor-toggle"' in response.text
        assert 'data-tip="Search wanted issues"' in response.text
        assert 'data-tip="Pause monitoring"' in response.text
        assert 'data-tip="Downloading"' in response.text
        assert 'data-tip-pos="left"' in response.text
        assert 'hx-post="/pull-list/' in response.text
        assert 'hx-target="#pull-list-results-body"' in response.text
        assert 'hx-include="#pull-list-filter-form"' in response.text
        assert 'hx-put="/api/v1/series/' not in response.text

    async def test_pull_list_series_links_preserve_their_origin(
        self,
        authenticated_client,
        sec_db,
    ) -> None:  # type: ignore[no-untyped-def]
        series_id = await _seed_pull_list_series(sec_db)

        return_url = "/pull-list?filter=wanted&search=Extremely&sort=-wanted&page=1&per_page=50"
        response = await authenticated_client.get(return_url)

        assert response.status_code == 200
        match = re.search(rf'href="(/series/{series_id}\?[^\"]+)"', response.text)
        assert match is not None
        link_query = parse_qs(urlparse(unescape(match.group(1))).query)
        assert link_query == {"from": ["pull-list"], "return_to": [return_url]}

    async def test_pull_list_pause_action_updates_monitoring_and_removes_row(
        self,
        authenticated_client,
        sec_db,
    ) -> None:  # type: ignore[no-untyped-def]
        series_id = await _seed_pull_list_series(sec_db)

        response = await authenticated_client.post(
            f"/pull-list/{series_id}/monitoring",
            data={"monitored": "false", "page": "1", "sort": "title", "filter": "", "search": ""},
            headers={"HX-Request": "true", **_csrf_header_for(authenticated_client)},
        )

        assert response.status_code == 200
        assert f'data-testid="pull-list-row-{series_id}"' not in response.text
        assert 'data-testid="pull-list-empty"' in response.text
        assert re.search(
            r'<span class="page-dock-status-label">monitored</span>\s*'
            r'<strong class="page-dock-status-value">0</strong>',
            response.text,
        )
        assert re.search(
            r'<span class="page-dock-status-label">paused</span>\s*'
            r'<strong class="page-dock-status-value">1</strong>',
            response.text,
        )

        async with sec_db() as session:
            series = await session.get(Series, series_id)
            assert series is not None
            assert series.monitored is False
