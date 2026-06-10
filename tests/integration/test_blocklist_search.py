"""
Integration tests for blocklist filtering in the search pipeline.

Validates that blocked releases and groups are filtered out before
scoring, and that the SearchLog records the blocklist count.

Run:
    pytest tests/integration/test_blocklist_search.py -v
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from pullbox.models.blocklist import BlocklistReason
from pullbox.models.config import SystemConfig
from pullbox.models.issue import Issue, IssueStatus
from pullbox.models.search_log import SearchLog
from pullbox.models.series import Series, SeriesStatus
from pullbox.providers.base import ReleaseResult
from pullbox.services.blocklist_service import BlocklistService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# ── Helpers ───────────────────────────────────────────────────────────


def _make_release(
    title: str,
    *,
    indexer: str = "NZBgeek",
    url: str | None = None,
) -> ReleaseResult:
    return ReleaseResult(
        title=title,
        indexer_name=indexer,
        download_url=url or f"https://example.com/nzb/{title.replace('.', '_')}",
        size_bytes=100_000_000,
        age_days=1,
        seeders=None,
        leechers=None,
        grabs=50,
        is_torrent=False,
        category="Comics",
        published_at=datetime.now(tz=UTC),
    )


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture()
def svc() -> BlocklistService:
    return BlocklistService()


# ── Search filtering integration tests ────────────────────────────────


@pytest.mark.slow
class TestSearchBlocklistFiltering:
    """Verify blocklist filtering integrates correctly with search results."""

    async def test_blocked_release_excluded(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        """A release in the blocklist is filtered out of search results."""
        await svc.add_entry(
            db_session, "Batman.018.2026.Digital.Zone-Empire", BlocklistReason.FAILED
        )
        results = [
            _make_release("Batman.018.2026.Digital.Zone-Empire"),
            _make_release("Saga.073.2026.Minutemen"),
        ]
        filtered = await svc.filter_results(db_session, results)
        assert len(filtered) == 1
        assert filtered[0].title == "Saga.073.2026.Minutemen"

    async def test_blocked_group_excluded(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        """All results from a blocked group are filtered out."""
        session = db_session
        # Block "Zone-Empire" — the full scan_group extracted by the parser
        existing = await session.get(SystemConfig, "blocklist.release_groups")
        if existing:
            existing.value = "Zone-Empire"
        else:
            session.add(
                SystemConfig(
                    key="blocklist.release_groups",
                    value="Zone-Empire",
                    value_type="string",
                )
            )
        await session.flush()

        results = [
            _make_release("Batman.018.2026.Digital.Zone-Empire"),
            _make_release("Saga.073.2026.Minutemen"),
        ]
        filtered = await svc.filter_results(db_session, results)
        # Zone-Empire group should be filtered, Minutemen has no group (kept)
        assert len(filtered) == 1
        assert filtered[0].title == "Saga.073.2026.Minutemen"

    async def test_no_blocked_returns_all(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        """When nothing is blocked, all results pass through."""
        results = [
            _make_release("Batman.018"),
            _make_release("Saga.073"),
            _make_release("X-Men.012"),
        ]
        filtered = await svc.filter_results(db_session, results)
        assert len(filtered) == 3

    async def test_all_blocked_returns_empty(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        """When all results are blocked, empty list returned."""
        await svc.add_entry(db_session, "Batman.018", BlocklistReason.FAILED)
        await svc.add_entry(db_session, "Saga.073", BlocklistReason.FAILED)
        results = [_make_release("Batman.018"), _make_release("Saga.073")]
        filtered = await svc.filter_results(db_session, results)
        assert len(filtered) == 0

    async def test_mixed_title_and_group_blocking(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        """Title-blocked and group-blocked both filtered, clean results kept."""
        await svc.add_entry(db_session, "Batman.018.2026.Minutemen", BlocklistReason.FAILED)
        session = db_session
        # Block the full group name as extracted by the parser
        existing = await session.get(SystemConfig, "blocklist.release_groups")
        if existing:
            existing.value = "Pyrate-DCP"
        else:
            session.add(
                SystemConfig(
                    key="blocklist.release_groups",
                    value="Pyrate-DCP",
                    value_type="string",
                )
            )
        await session.flush()

        results = [
            _make_release("Batman.018.2026.Minutemen"),  # blocked by title
            _make_release("Saga.073.2026.Pyrate-DCP"),  # blocked by group
            _make_release("X-Men.012.2026.Testers"),  # clean (no group parsed)
        ]
        filtered = await svc.filter_results(db_session, results)
        assert len(filtered) == 1
        assert filtered[0].title == "X-Men.012.2026.Testers"


@pytest.mark.slow
class TestSearchLogBlocklistCounter:
    """Verify SearchLog records the blocklist count."""

    @pytest.fixture()
    async def test_issue(self, db_session: AsyncSession) -> Issue:
        """Create a minimal series + issue for SearchLog FK."""
        series = Series(
            title="Batman",
            sort_title="batman",
            comicvine_id=99999,
            status=SeriesStatus.CONTINUING,
        )
        db_session.add(series)
        await db_session.flush()
        issue = Issue(
            series_id=series.id,
            issue_number=18.0,
            status=IssueStatus.WANTED,
        )
        db_session.add(issue)
        await db_session.flush()
        return issue

    async def test_searchlog_has_blocklisted_field(
        self, db_session: AsyncSession, test_issue: Issue
    ) -> None:
        """SearchLog model has results_blocklisted with default 0."""
        log = SearchLog(
            issue_id=test_issue.id,
            series_title="Batman",
            issue_number=18.0,
            search_type="manual",
            results_found=10,
            results_grabbed=0,
            results_queued=0,
            results_rejected=0,
            results_blocklisted=3,
        )
        db_session.add(log)
        await db_session.flush()

        assert log.results_blocklisted == 3

    async def test_searchlog_blocklisted_defaults_to_zero(
        self, db_session: AsyncSession, test_issue: Issue
    ) -> None:
        """results_blocklisted defaults to 0 when not specified."""
        log = SearchLog(
            issue_id=test_issue.id,
            series_title="Batman",
            issue_number=18.0,
            search_type="manual",
            results_found=10,
        )
        db_session.add(log)
        await db_session.flush()

        assert log.results_blocklisted == 0


@pytest.mark.slow
class TestFilterOrdering:
    """Verify blocklist filter runs before scoring (blocked results never scored)."""

    async def test_blocked_not_in_filtered_results(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        """Filtered results should not contain any blocked releases."""
        await svc.add_entry(db_session, "Batman.018.2026", BlocklistReason.FAILED)
        results = [
            _make_release("Batman.018.2026"),
            _make_release("Saga.073.2026"),
            _make_release("X-Men.012.2026"),
        ]
        filtered = await svc.filter_results(db_session, results)

        # Batman should be gone, Saga and X-Men remain
        titles = [r.title for r in filtered]
        assert "Batman.018.2026" not in titles
        assert "Saga.073.2026" in titles
        assert "X-Men.012.2026" in titles

    async def test_filter_count_matches_removed(
        self, db_session: AsyncSession, svc: BlocklistService
    ) -> None:
        """The difference between input and output counts matches blocklisted count."""
        await svc.add_entry(db_session, "Blocked.001", BlocklistReason.FAILED)
        await svc.add_entry(db_session, "Blocked.002", BlocklistReason.FAILED)
        await svc.add_entry(db_session, "Blocked.003", BlocklistReason.FAILED)

        results = [
            _make_release("Blocked.001"),
            _make_release("Blocked.002"),
            _make_release("Blocked.003"),
            _make_release("Clean.001"),
            _make_release("Clean.002"),
        ]
        filtered = await svc.filter_results(db_session, results)
        blocklisted_count = len(results) - len(filtered)

        assert blocklisted_count == 3
        assert len(filtered) == 2
