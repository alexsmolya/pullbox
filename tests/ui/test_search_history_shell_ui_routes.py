"""Route-contract tests for the standardized search history shell."""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

import pytest

from pullbox.models.issue import Issue, IssueStatus, IssueType
from pullbox.models.search_log import SearchLog, SearchType
from pullbox.models.series import Series, SeriesStatus, SeriesType

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

pytest_plugins = ["conftest_security"]

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-search-history-shell-ui")


@pytest.mark.asyncio
class TestSearchHistoryShellRouteContracts:
    """Verify search history renders stable shell regions and partials."""

    async def test_search_history_renders_standardized_shell(
        self,
        authenticated_client,
    ) -> None:  # type: ignore[no-untyped-def]
        response = await authenticated_client.get("/search-history")

        assert response.status_code == 200
        assert 'data-testid="search-history-page"' in response.text
        assert 'data-testid="search-history-content"' in response.text
        assert 'data-testid="search-history-header"' in response.text
        assert 'data-testid="search-history-header-metrics"' in response.text
        assert 'data-testid="search-history-gauges"' in response.text
        assert 'data-testid="search-history-results"' in response.text
        assert 'data-testid="search-history-filters"' in response.text
        assert 'data-testid="search-history-filter-form"' in response.text
        assert 'data-testid="search-history-results-body"' in response.text
        assert 'data-testid="search-history-search-field"' in response.text
        assert 'data-testid="search-history-search-input"' in response.text
        assert 'data-testid="search-history-search-clear"' in response.text
        assert 'data-testid="search-history-search-history-panel"' in response.text
        assert 'data-search-field-contract="baseline-v2"' in response.text
        assert 'data-search-field-mode="remote"' in response.text
        assert 'data-search-history-key="pullbox.searchHistory.searchLogs"' in response.text
        assert 'data-testid="search-history-filter-type"' in response.text
        assert 'data-testid="search-history-filter-confidence"' in response.text
        assert 'id="search-history-clear-slot"' in response.text
        assert 'data-testid="page-footer-dock"' in response.text
        assert 'data-testid="page-dock-inner"' in response.text
        assert 'data-testid="page-dock-status"' in response.text
        assert 'class="downloads-table-wrap"' in response.text
        assert 'data-dropdown-select-contract="v1"' in response.text
        assert (
            'data-testid="search-history-table"' in response.text
            or 'data-testid="search-history-empty"' in response.text
        )

    async def test_search_history_hx_request_returns_results_only(
        self,
        authenticated_client,
    ) -> None:  # type: ignore[no-untyped-def]
        response = await authenticated_client.get(
            "/search-history?search_type=manual",
            headers={"HX-Request": "true"},
        )

        assert response.status_code == 200
        assert 'id="search-history-header-metrics"' in response.text
        assert 'id="page-footer-dock"' in response.text
        assert 'id="search-history-clear-slot"' in response.text
        assert 'data-testid="search-history-results-body"' in response.text
        assert 'data-testid="search-history-page"' not in response.text
        assert 'data-testid="search-history-filter-form"' not in response.text

    async def test_search_history_lazy_loads_full_rejected_diagnostics(
        self,
        authenticated_client,
        sec_db: async_sessionmaker[AsyncSession],
    ) -> None:  # type: ignore[no-untyped-def]
        async with sec_db() as session:
            series = Series(
                comicvine_id=1001,
                title="Absolute Flash",
                sort_title="absolute flash",
                year_start=2025,
                status=SeriesStatus.CONTINUING,
                series_type=SeriesType.STANDARD,
                monitored=True,
                issue_count=1,
            )
            session.add(series)
            await session.flush()
            issue = Issue(
                series_id=series.id,
                comicvine_id=2001,
                issue_number=1,
                title="Issue #1",
                status=IssueStatus.WANTED,
                issue_type=IssueType.ISSUE,
            )
            session.add(issue)
            await session.flush()
            log = SearchLog(
                issue_id=issue.id,
                series_title="Absolute Flash",
                issue_number=1,
                search_type=SearchType.MANUAL,
                results_found=5,
                results_rejected=5,
                details={
                    "query_diagnostics": [
                        {
                            "query": "Absolute Flash #001",
                            "elapsed_ms": 1250,
                            "result_count": 3,
                            "indexers": [
                                {
                                    "indexer": "MyAnonamouse",
                                    "elapsed_ms": 1200,
                                    "result_count": 3,
                                    "filtered_count": 0,
                                    "status": "completed",
                                }
                            ],
                        }
                    ],
                    "top_rejected": [
                        {
                            "title": "Absolute Flashpoint 001",
                            "indexer": "NZBgeek",
                            "reason": "Series mismatch",
                        },
                        {
                            "title": "Absolute Flashpoint 002",
                            "indexer": "NZBgeek",
                            "reason": "Series mismatch",
                        },
                        {
                            "title": "Absolute Flashpoint 003",
                            "indexer": "NZBgeek",
                            "reason": "Series mismatch",
                        },
                    ],
                    "rejected": [
                        {"title": f"Absolute Flashpoint 00{index}"} for index in range(1, 6)
                    ],
                    "rejected_diagnostics_count": 5,
                    "rejected_diagnostics_truncated": False,
                },
                best_confidence=None,
            )
            session.add(log)
            await session.flush()
            log_id = log.id
            await session.commit()

        response = await authenticated_client.get("/search-history")

        assert response.status_code == 200
        assert "Query Timing" not in response.text
        assert "Absolute Flash #001" not in response.text
        assert "query_diagnostics" not in response.text
        assert "rejected_diagnostics_count" not in response.text
        assert 'data-testid="search-history-detail-placeholder"' in response.text
        assert 'x-data="searchHistoryRowData({' in response.text
        assert f"detailUrl: '/htmx/search-history/logs/{log_id}/detail'" in response.text
        assert f"detailTarget: '#search-history-detail-content-{log_id}'" in response.text
        assert "Loading diagnostics" in response.text
        assert response.text.count("search-log-data-") == 0

        detail_response = await authenticated_client.get(
            f"/htmx/search-history/logs/{log_id}/detail"
        )

        assert detail_response.status_code == 200
        assert "Query Timing" in detail_response.text
        assert "Absolute Flash #001" in detail_response.text
        assert "MyAnonamouse" in detail_response.text
        assert "1.2s" in detail_response.text
        assert "+ 3 more rejected candidates in the exported log." in detail_response.text
        assert "query_diagnostics" in detail_response.text
        assert "rejected_diagnostics_count" in detail_response.text

    async def test_search_history_detail_route_404s_for_missing_log(
        self,
        authenticated_client,
    ) -> None:  # type: ignore[no-untyped-def]
        response = await authenticated_client.get("/htmx/search-history/logs/999999/detail")

        assert response.status_code == 404

    async def test_search_history_running_detail_loads_status_copy(
        self,
        authenticated_client,
        sec_db: async_sessionmaker[AsyncSession],
    ) -> None:  # type: ignore[no-untyped-def]
        async with sec_db() as session:
            series = Series(
                comicvine_id=3001,
                title="Absolute Superman",
                sort_title="absolute superman",
                year_start=2025,
                status=SeriesStatus.CONTINUING,
                series_type=SeriesType.STANDARD,
                monitored=True,
                issue_count=1,
            )
            session.add(series)
            await session.flush()
            issue = Issue(
                series_id=series.id,
                comicvine_id=4001,
                issue_number=12,
                title="Issue #12",
                status=IssueStatus.WANTED,
                issue_type=IssueType.ISSUE,
            )
            session.add(issue)
            await session.flush()
            log = SearchLog(
                issue_id=issue.id,
                series_title="Absolute Superman",
                issue_number=12,
                search_type=SearchType.BULK,
                results_found=0,
                results_grabbed=0,
                results_queued=0,
                results_rejected=0,
                details={"run_state": "running", "task_id": "search_series_1_123"},
                best_confidence=None,
            )
            session.add(log)
            await session.flush()
            log_id = log.id
            await session.commit()

        response = await authenticated_client.get(f"/htmx/search-history/logs/{log_id}/detail")

        assert response.status_code == 200
        assert "Search is still running for this issue." in response.text

    async def test_search_history_running_rows_poll_and_render_status(
        self,
        authenticated_client,
        sec_db: async_sessionmaker[AsyncSession],
    ) -> None:  # type: ignore[no-untyped-def]
        async with sec_db() as session:
            series = Series(
                comicvine_id=3001,
                title="Absolute Superman",
                sort_title="absolute superman",
                year_start=2025,
                status=SeriesStatus.CONTINUING,
                series_type=SeriesType.STANDARD,
                monitored=True,
                issue_count=1,
            )
            session.add(series)
            await session.flush()
            issue = Issue(
                series_id=series.id,
                comicvine_id=4001,
                issue_number=12,
                title="Issue #12",
                status=IssueStatus.WANTED,
                issue_type=IssueType.ISSUE,
            )
            session.add(issue)
            await session.flush()
            session.add(
                SearchLog(
                    issue_id=issue.id,
                    series_title="Absolute Superman",
                    issue_number=12,
                    search_type=SearchType.BULK,
                    results_found=0,
                    results_grabbed=0,
                    results_queued=0,
                    results_rejected=0,
                    details={"run_state": "running", "task_id": "search_series_1_123"},
                    best_confidence=None,
                )
            )
            await session.commit()

        response = await authenticated_client.get("/search-history")

        assert response.status_code == 200
        assert 'hx-get="/search-history"' in response.text
        assert 'hx-trigger="every 2s [window.searchHistoryRefreshEnabled()]"' in response.text
        assert 'hx-sync="this:replace"' in response.text
        assert (
            "x-bind:data-search-history-expanded=\"expanded ? 'true' : 'false'\"" in response.text
        )
        assert "Searching" in response.text
        assert "Search is still running for this issue." not in response.text
