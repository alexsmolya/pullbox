"""Tests for two-pass search for non-standard types — ESM Phase 3, Task 3.3.

Covers:
- Pass 1 HIGH match auto-grabs (if type threshold allows)
- Pass 1 LOW match queues
- Fallback pass matches follow the normal auto-grab threshold rules
- Deduplication across passes (same URL not queued twice)
- Standard ISSUE type skips two-pass
- Config toggle disables two-pass

Run:
    pytest tests/unit/test_two_pass_search.py -v
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from pullbox.models import Base
from pullbox.models.issue import Issue, IssueStatus, IssueType
from pullbox.models.library import MatchConfidence
from pullbox.models.series import Series, SeriesStatus, SeriesType
from pullbox.providers.base import ReleaseResult

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


# ── Helpers ──────────────────────────────────────────────────────────


def _make_release(
    title: str = "Batman 001 (2016).cbz",
    url: str = "https://indexer.example.com/dl/test",
) -> ReleaseResult:
    return ReleaseResult(
        title=title,
        indexer_name="NZBgeek",
        download_url=url,
        size_bytes=100_000_000,
        age_days=2,
        seeders=None,
        leechers=None,
        grabs=None,
        is_torrent=False,
        category=None,
        published_at=None,
    )


def _make_validation(confidence: MatchConfidence = MatchConfidence.HIGH) -> MagicMock:
    v = MagicMock()
    v.confidence = confidence
    v.is_match = True
    v.parsed = MagicMock()
    v.parsed.series_name = "Batman"
    v.parsed.issue_number = 1.0
    v.parsed.year = 2016
    v.parsed.issue_type = IssueType.TPB
    v.series_similarity = 0.98
    v.issue_match = True
    v.year_match = True
    v.issue_type_match = True
    v.rejection_reason = None
    return v


def _common_patches(factory: object) -> dict[str, MagicMock | AsyncMock]:
    """Create common mock setup for two-pass tests."""
    return {
        "factory_patch": patch(
            "pullbox.tasks.search_task.get_session_factory",
            return_value=factory,
        ),
        "registry_patch": patch(
            "pullbox.tasks.search_task.build_registry",
            new_callable=AsyncMock,
            return_value=(MagicMock(), {}),
        ),
    }


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
async def tpb_db() -> AsyncGenerator[dict[str, object], None]:
    """In-memory DB with a series and a wanted TPB issue."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_fk(dbapi_conn: object, _rec: object) -> None:
        dbapi_conn.execute("PRAGMA foreign_keys=ON")  # type: ignore[union-attr]

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        series = Series(
            comicvine_id=99900,
            title="Batman",
            sort_title="Batman",
            year_start=2016,
            status=SeriesStatus.CONTINUING,
            series_type=SeriesType.STANDARD,
            monitored=True,
            issue_count=1,
        )
        session.add(series)
        await session.flush()

        issue = Issue(
            series_id=series.id,
            comicvine_id=50001,
            issue_number=1.0,
            title="TPB #1",
            status=IssueStatus.WANTED,
            issue_type=IssueType.TPB,
        )
        session.add(issue)
        await session.commit()

        yield {
            "series_id": series.id,
            "issue_id": issue.id,
            "factory": factory,
        }

    await engine.dispose()


@pytest.fixture
async def issue_db() -> AsyncGenerator[dict[str, object], None]:
    """In-memory DB with a series and a wanted standard ISSUE."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_fk(dbapi_conn: object, _rec: object) -> None:
        dbapi_conn.execute("PRAGMA foreign_keys=ON")  # type: ignore[union-attr]

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        series = Series(
            comicvine_id=99901,
            title="Batman",
            sort_title="Batman",
            year_start=2016,
            status=SeriesStatus.CONTINUING,
            series_type=SeriesType.STANDARD,
            monitored=True,
            issue_count=1,
        )
        session.add(series)
        await session.flush()

        issue = Issue(
            series_id=series.id,
            comicvine_id=50002,
            issue_number=5.0,
            title="Issue #5",
            status=IssueStatus.WANTED,
            issue_type=IssueType.ISSUE,
        )
        session.add(issue)
        await session.commit()

        yield {
            "series_id": series.id,
            "issue_id": issue.id,
            "factory": factory,
        }

    await engine.dispose()


# ── Tests ────────────────────────────────────────────────────────────


class TestTwoPassSearch:
    """Tests for two-pass search routing in search_series_issues."""

    @pytest.mark.asyncio
    async def test_first_pass_high_match_auto_grabs(self, tpb_db: dict[str, object]) -> None:
        """HIGH confidence from pass 1 auto-grabs (if type threshold allows)."""
        series_id = tpb_db["series_id"]
        factory = tpb_db["factory"]

        mock_release = _make_release()
        # TPB default threshold is "never", so even HIGH gets queued.
        # Use custom thresholds to allow auto-grab for this test.
        mock_validation = _make_validation(MatchConfidence.HIGH)

        with (
            patch(
                "pullbox.tasks.search_task.get_session_factory",
                return_value=factory,
            ),
            patch(
                "pullbox.tasks.search_task.build_registry",
                new_callable=AsyncMock,
                return_value=(MagicMock(), {}),
            ),
            patch("pullbox.tasks.search_task.SearchService") as mock_search_cls,
            patch("pullbox.tasks.search_task.DownloadService") as mock_download_cls,
            patch("pullbox.tasks.search_task.InterventionService") as mock_intervention_cls,
            patch("pullbox.tasks.search_task.ReleaseValidator") as mock_validator_cls,
        ):
            mock_search = mock_search_cls.return_value
            # Pass 1 returns results
            mock_search.search_for_issue = AsyncMock(return_value=[mock_release])
            mock_search.evaluate_results = MagicMock(return_value=mock_release)

            mock_download = mock_download_cls.return_value
            mock_download.send_to_client = AsyncMock(return_value=MagicMock())

            mock_intervention = mock_intervention_cls.return_value
            mock_intervention.create_pending_match = AsyncMock()
            mock_intervention.has_pending_for_issue = AsyncMock(return_value=False)

            mock_validator_cls.return_value.validate_results = MagicMock(
                return_value=[mock_validation]
            )

            from pullbox.tasks.search_task import search_series_issues

            # Override thresholds to allow TPB auto-grab at HIGH
            with patch(
                "pullbox.tasks.search_task.DEFAULT_TYPE_THRESHOLDS",
                {**{"tpb": "high"}, "issue": "medium"},
            ):
                result = await search_series_issues(series_id)

            # Pass 1 found HIGH → auto-grabbed, no pass 2 needed
            mock_download.send_to_client.assert_called_once()
            assert result["sent"] >= 1
            # search_for_issue called once (pass 1 only, no pass 2)
            assert mock_search.search_for_issue.call_count == 1

    @pytest.mark.asyncio
    async def test_first_pass_low_match_queues(self, tpb_db: dict[str, object]) -> None:
        """LOW confidence from pass 1 routes to intervention queue."""
        series_id = tpb_db["series_id"]
        factory = tpb_db["factory"]

        mock_release = _make_release()
        mock_validation = _make_validation(MatchConfidence.LOW)

        with (
            patch(
                "pullbox.tasks.search_task.get_session_factory",
                return_value=factory,
            ),
            patch(
                "pullbox.tasks.search_task.build_registry",
                new_callable=AsyncMock,
                return_value=(MagicMock(), {}),
            ),
            patch("pullbox.tasks.search_task.SearchService") as mock_search_cls,
            patch("pullbox.tasks.search_task.DownloadService") as mock_download_cls,
            patch("pullbox.tasks.search_task.InterventionService") as mock_intervention_cls,
            patch("pullbox.tasks.search_task.ReleaseValidator") as mock_validator_cls,
        ):
            mock_search = mock_search_cls.return_value
            mock_search.search_for_issue = AsyncMock(return_value=[mock_release])
            mock_search.evaluate_results = MagicMock(return_value=mock_release)

            mock_download = mock_download_cls.return_value
            mock_download.send_to_client = AsyncMock()

            mock_intervention = mock_intervention_cls.return_value
            mock_intervention.create_pending_match = AsyncMock(return_value=MagicMock())
            mock_intervention.has_pending_for_issue = AsyncMock(return_value=False)

            mock_validator_cls.return_value.validate_results = MagicMock(
                return_value=[mock_validation]
            )

            from pullbox.tasks.search_task import search_series_issues

            result = await search_series_issues(series_id)

            # LOW confidence with TPB "never" threshold → queued
            mock_download.send_to_client.assert_not_called()
            mock_intervention.create_pending_match.assert_called_once()
            assert result["queued"] >= 1

    @pytest.mark.asyncio
    async def test_second_pass_can_auto_grab_when_threshold_allows(
        self,
        tpb_db: dict[str, object],
    ) -> None:
        """Fallback-pass HIGH confidence results honor the normal auto-grab thresholds."""
        series_id = tpb_db["series_id"]
        factory = tpb_db["factory"]

        mock_release_pass2 = _make_release(
            title="Batman 001 (2016) Generic.cbz",
            url="https://indexer.example.com/dl/generic",
        )
        mock_validation = _make_validation(MatchConfidence.HIGH)

        with (
            patch(
                "pullbox.tasks.search_task.get_session_factory",
                return_value=factory,
            ),
            patch(
                "pullbox.tasks.search_task.build_registry",
                new_callable=AsyncMock,
                return_value=(MagicMock(), {}),
            ),
            patch("pullbox.tasks.search_task.SearchService") as mock_search_cls,
            patch("pullbox.tasks.search_task.DownloadService") as mock_download_cls,
            patch("pullbox.tasks.search_task.InterventionService") as mock_intervention_cls,
            patch("pullbox.tasks.search_task.ReleaseValidator") as mock_validator_cls,
        ):
            mock_search = mock_search_cls.return_value
            # Pass 1 returns no results, pass 2 returns results
            mock_search.search_for_issue = AsyncMock(side_effect=[[], [mock_release_pass2]])
            mock_search.evaluate_results = MagicMock(return_value=mock_release_pass2)

            mock_download = mock_download_cls.return_value
            mock_download.send_to_client = AsyncMock()

            mock_intervention = mock_intervention_cls.return_value
            mock_intervention.create_pending_match = AsyncMock(return_value=MagicMock())
            mock_intervention.has_pending_for_issue = AsyncMock(return_value=False)

            mock_validator_cls.return_value.validate_results = MagicMock(
                return_value=[mock_validation]
            )

            from pullbox.tasks.search_task import search_series_issues

            # Even with thresholds that would allow auto-grab
            with patch(
                "pullbox.tasks.search_task.DEFAULT_TYPE_THRESHOLDS",
                {**{"tpb": "high"}, "issue": "medium"},
            ):
                result = await search_series_issues(series_id)

            # Fallback result now follows the same threshold contract as manual search.
            mock_download.send_to_client.assert_called_once()
            mock_intervention.create_pending_match.assert_not_called()
            assert result["sent"] >= 1
            # search_for_issue called twice (pass 1 + pass 2)
            assert mock_search.search_for_issue.call_count == 2

    @pytest.mark.asyncio
    async def test_no_duplicate_pending(self, tpb_db: dict[str, object]) -> None:
        """Pass 2 skips creating pending if pass 1 already queued for same issue."""
        series_id = tpb_db["series_id"]
        factory = tpb_db["factory"]

        mock_release = _make_release()
        mock_validation = _make_validation(MatchConfidence.LOW)

        with (
            patch(
                "pullbox.tasks.search_task.get_session_factory",
                return_value=factory,
            ),
            patch(
                "pullbox.tasks.search_task.build_registry",
                new_callable=AsyncMock,
                return_value=(MagicMock(), {}),
            ),
            patch("pullbox.tasks.search_task.SearchService") as mock_search_cls,
            patch("pullbox.tasks.search_task.DownloadService") as mock_download_cls,
            patch("pullbox.tasks.search_task.InterventionService") as mock_intervention_cls,
            patch("pullbox.tasks.search_task.ReleaseValidator") as mock_validator_cls,
        ):
            mock_search = mock_search_cls.return_value
            # Pass 1: has results, LOW confidence → queued
            # Pass 2: would also have results, but pass 1 already found a match
            mock_search.search_for_issue = AsyncMock(return_value=[mock_release])
            mock_search.evaluate_results = MagicMock(return_value=mock_release)

            mock_download = mock_download_cls.return_value
            mock_download.send_to_client = AsyncMock()

            mock_intervention = mock_intervention_cls.return_value
            mock_intervention.create_pending_match = AsyncMock(return_value=MagicMock())
            mock_intervention.has_pending_for_issue = AsyncMock(return_value=False)

            mock_validator_cls.return_value.validate_results = MagicMock(
                return_value=[mock_validation]
            )

            from pullbox.tasks.search_task import search_series_issues

            result = await search_series_issues(series_id)

            # Pass 1 queued the match, pass 2 not executed
            mock_intervention.create_pending_match.assert_called_once()
            # search_for_issue called once (pass 1 matched, no pass 2)
            assert mock_search.search_for_issue.call_count == 1
            assert result["queued"] == 1

    @pytest.mark.asyncio
    async def test_standard_issue_skips_two_pass(self, issue_db: dict[str, object]) -> None:
        """Standard ISSUE type does NOT use two-pass — single pass only."""
        series_id = issue_db["series_id"]
        factory = issue_db["factory"]

        with (
            patch(
                "pullbox.tasks.search_task.get_session_factory",
                return_value=factory,
            ),
            patch(
                "pullbox.tasks.search_task.build_registry",
                new_callable=AsyncMock,
                return_value=(MagicMock(), {}),
            ),
            patch("pullbox.tasks.search_task.SearchService") as mock_search_cls,
            patch("pullbox.tasks.search_task.DownloadService") as mock_download_cls,
            patch("pullbox.tasks.search_task.InterventionService") as mock_intervention_cls,
            patch("pullbox.tasks.search_task.ReleaseValidator") as mock_validator_cls,
        ):
            mock_search = mock_search_cls.return_value
            # No results from pass 1
            mock_search.search_for_issue = AsyncMock(return_value=[])
            mock_search.evaluate_results = MagicMock(return_value=None)

            mock_download = mock_download_cls.return_value
            mock_download.send_to_client = AsyncMock()

            mock_intervention = mock_intervention_cls.return_value
            mock_intervention.create_pending_match = AsyncMock()
            mock_intervention.has_pending_for_issue = AsyncMock(return_value=False)

            mock_validator_cls.return_value.validate_results = MagicMock(return_value=[])

            from pullbox.tasks.search_task import search_series_issues

            await search_series_issues(series_id)

            # Standard ISSUE: only 1 call, no pass 2
            assert mock_search.search_for_issue.call_count == 1

    @pytest.mark.asyncio
    async def test_disabled_when_config_off(self, tpb_db: dict[str, object]) -> None:
        """When search_two_pass_enabled=false, non-standard uses single pass."""
        series_id = tpb_db["series_id"]
        factory = tpb_db["factory"]

        # Seed config to disable two-pass
        async with factory() as session:
            from pullbox.models.config import SystemConfig

            session.add(SystemConfig(key="search_two_pass_enabled", value="false"))
            await session.commit()

        with (
            patch(
                "pullbox.tasks.search_task.get_session_factory",
                return_value=factory,
            ),
            patch(
                "pullbox.tasks.search_task.build_registry",
                new_callable=AsyncMock,
                return_value=(MagicMock(), {}),
            ),
            patch("pullbox.tasks.search_task.SearchService") as mock_search_cls,
            patch("pullbox.tasks.search_task.DownloadService") as mock_download_cls,
            patch("pullbox.tasks.search_task.InterventionService") as mock_intervention_cls,
            patch("pullbox.tasks.search_task.ReleaseValidator") as mock_validator_cls,
        ):
            mock_search = mock_search_cls.return_value
            # Pass 1 no results
            mock_search.search_for_issue = AsyncMock(return_value=[])
            mock_search.evaluate_results = MagicMock(return_value=None)

            mock_download = mock_download_cls.return_value
            mock_download.send_to_client = AsyncMock()

            mock_intervention = mock_intervention_cls.return_value
            mock_intervention.create_pending_match = AsyncMock()
            mock_intervention.has_pending_for_issue = AsyncMock(return_value=False)

            mock_validator_cls.return_value.validate_results = MagicMock(return_value=[])

            from pullbox.tasks.search_task import search_series_issues

            await search_series_issues(series_id)

            # Two-pass disabled: only 1 search call even for TPB with no results
            assert mock_search.search_for_issue.call_count == 1

    @pytest.mark.asyncio
    async def test_pass2_no_match_logs_skip(self, tpb_db: dict[str, object]) -> None:
        """Pass 2 with no match logs and skips — no pending match created."""
        series_id = tpb_db["series_id"]
        factory = tpb_db["factory"]

        with (
            patch(
                "pullbox.tasks.search_task.get_session_factory",
                return_value=factory,
            ),
            patch(
                "pullbox.tasks.search_task.build_registry",
                new_callable=AsyncMock,
                return_value=(MagicMock(), {}),
            ),
            patch("pullbox.tasks.search_task.SearchService") as mock_search_cls,
            patch("pullbox.tasks.search_task.DownloadService") as mock_download_cls,
            patch("pullbox.tasks.search_task.InterventionService") as mock_intervention_cls,
            patch("pullbox.tasks.search_task.ReleaseValidator") as mock_validator_cls,
        ):
            mock_search = mock_search_cls.return_value
            # Both passes return no results
            mock_search.search_for_issue = AsyncMock(return_value=[])
            mock_search.evaluate_results = MagicMock(return_value=None)

            mock_download = mock_download_cls.return_value
            mock_download.send_to_client = AsyncMock()

            mock_intervention = mock_intervention_cls.return_value
            mock_intervention.create_pending_match = AsyncMock()
            mock_intervention.has_pending_for_issue = AsyncMock(return_value=False)

            mock_validator_cls.return_value.validate_results = MagicMock(return_value=[])

            from pullbox.tasks.search_task import search_series_issues

            result = await search_series_issues(series_id)

            # Pass 1 no match + pass 2 no match → nothing sent/queued
            mock_download.send_to_client.assert_not_called()
            mock_intervention.create_pending_match.assert_not_called()
            # 2 calls: pass 1 (type-specific) + pass 2 (generic)
            assert mock_search.search_for_issue.call_count == 2
            assert result["sent"] == 0
            assert result["queued"] == 0
