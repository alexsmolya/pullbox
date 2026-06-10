"""Tests for search routing — ESM Phase 2, Task 2.3.

Covers:
- should_auto_grab() decision logic (6 tests)
- search_series_issues() routing: auto-grab vs queue vs discard (4 tests)

Run:
    pytest tests/unit/test_search_routing.py -v
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
from pullbox.services.search_service import should_auto_grab

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


# ── Helpers ──────────────────────────────────────────────────────────


def _make_release(title: str = "Batman 001 (2016).cbz") -> ReleaseResult:
    return ReleaseResult(
        title=title,
        indexer_name="NZBgeek",
        download_url="https://indexer.example.com/dl/test",
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
    v.parsed.issue_type = IssueType.ISSUE
    v.series_similarity = 0.98
    v.issue_match = True
    v.year_match = True
    v.issue_type_match = True
    v.rejection_reason = None
    return v


def _common_patches(
    factory: object,
) -> tuple[MagicMock, MagicMock, MagicMock, MagicMock, MagicMock, MagicMock]:
    """Create common mock objects for routing tests.

    Returns (patches_context, mock_search, mock_download, mock_intervention,
    mock_validator_cls, mock_validator).
    """
    raise NotImplementedError  # Helpers are inline in each test


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
async def routing_db() -> AsyncGenerator[dict[str, object], None]:
    """In-memory DB with a series and a wanted issue for routing tests."""
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
            title="Issue #1",
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


# ── TestAutoGrabDecision ─────────────────────────────────────────────


class TestAutoGrabDecision:
    """Tests for the should_auto_grab() routing decision function."""

    def test_high_confidence_auto_grabs(self) -> None:
        """HIGH confidence with threshold='high' → auto-grab."""
        assert should_auto_grab(MatchConfidence.HIGH, IssueType.ISSUE, {}, "high") is True

    def test_medium_below_high_threshold_queues(self) -> None:
        """MEDIUM confidence with threshold='high' → queue."""
        assert should_auto_grab(MatchConfidence.MEDIUM, IssueType.ISSUE, {}, "high") is False

    def test_medium_at_medium_threshold_auto_grabs(self) -> None:
        """MEDIUM confidence with threshold='medium' → auto-grab."""
        assert (
            should_auto_grab(MatchConfidence.MEDIUM, IssueType.ISSUE, {"issue": "medium"}, "high")
            is True
        )

    def test_low_always_queues_unless_threshold_low(self) -> None:
        """LOW confidence queues unless threshold='low'."""
        # LOW below medium threshold → queue
        assert should_auto_grab(MatchConfidence.LOW, IssueType.ISSUE, {}, "medium") is False
        # LOW at low threshold → auto-grab
        assert (
            should_auto_grab(MatchConfidence.LOW, IssueType.ISSUE, {"issue": "low"}, "high") is True
        )

    def test_never_threshold_always_queues(self) -> None:
        """Type with threshold='never' always queues regardless of confidence."""
        assert (
            should_auto_grab(MatchConfidence.HIGH, IssueType.ISSUE, {"issue": "never"}, "high")
            is False
        )

    def test_type_specific_threshold_override(self) -> None:
        """TPB with threshold='never' queues even if confidence is HIGH."""
        assert (
            should_auto_grab(MatchConfidence.HIGH, IssueType.TPB, {"tpb": "never"}, "high") is False
        )


# ── TestSearchTaskRouting ────────────────────────────────────────────


class TestSearchTaskRouting:
    """Tests for search_series_issues() match routing logic."""

    @pytest.mark.asyncio
    async def test_high_match_auto_grabbed(self, routing_db: dict[str, object]) -> None:
        """HIGH confidence match is sent to download client."""
        series_id = routing_db["series_id"]
        factory = routing_db["factory"]

        mock_release = _make_release()
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

            result = await search_series_issues(series_id)

            mock_download.send_to_client.assert_called_once()
            mock_intervention.create_pending_match.assert_not_called()
            assert result["sent"] >= 1

    @pytest.mark.asyncio
    async def test_low_match_queued(self, routing_db: dict[str, object]) -> None:
        """LOW confidence match is routed to intervention queue (below 'medium' threshold)."""
        series_id = routing_db["series_id"]
        factory = routing_db["factory"]

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

            mock_download.send_to_client.assert_not_called()
            mock_intervention.create_pending_match.assert_called_once()
            assert result["queued"] >= 1

    @pytest.mark.asyncio
    async def test_no_match_discarded(self, routing_db: dict[str, object]) -> None:
        """No matches → neither send_to_client nor create_pending_match called."""
        series_id = routing_db["series_id"]
        factory = routing_db["factory"]

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

            mock_download.send_to_client.assert_not_called()
            mock_intervention.create_pending_match.assert_not_called()

    @pytest.mark.asyncio
    async def test_existing_pending_not_duplicated(self, routing_db: dict[str, object]) -> None:
        """If issue already has pending match, skip creating another."""
        series_id = routing_db["series_id"]
        factory = routing_db["factory"]

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
            mock_intervention.create_pending_match = AsyncMock()
            # Already has a pending match
            mock_intervention.has_pending_for_issue = AsyncMock(return_value=True)

            mock_validator_cls.return_value.validate_results = MagicMock(
                return_value=[mock_validation]
            )

            from pullbox.tasks.search_task import search_series_issues

            await search_series_issues(series_id)

            mock_download.send_to_client.assert_not_called()
            mock_intervention.create_pending_match.assert_not_called()
