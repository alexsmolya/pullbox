"""Route-contract tests for the redesigned pull list page."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pullbox.models.issue import Issue, IssueStatus
from pullbox.models.publisher import Publisher
from pullbox.models.series import Series

pytest_plugins = ["conftest_security"]

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-pull-list-ui")


async def _seed_pull_list_series(
    factory,
) -> None:
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

        session.add_all(
            [
                Issue(series_id=series.id, issue_number=1, status=IssueStatus.OWNED),
                Issue(series_id=series.id, issue_number=2, status=IssueStatus.WANTED),
                Issue(series_id=series.id, issue_number=3, status=IssueStatus.DOWNLOADING),
            ]
        )
        await session.commit()


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
        assert 'data-tip="Search wanted issues"' in response.text
        assert 'data-tip="Pause monitoring"' in response.text
        assert 'data-tip="Downloading"' in response.text
        assert 'data-tip-pos="left"' in response.text
