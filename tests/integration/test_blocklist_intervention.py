"""
Integration tests for reject-to-blocklist from the intervention queue.

Validates that rejecting a pending match adds the release to the blocklist.

Run:
    pytest tests/integration/test_blocklist_intervention.py -v
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from pullbox.models.blocklist import BlocklistEntry, BlocklistReason
from pullbox.models.issue import Issue, IssueStatus
from pullbox.models.pending_match import PendingMatch, PendingMatchStatus
from pullbox.models.series import Series, SeriesStatus
from pullbox.services.intervention_service import InterventionService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture()
async def test_series(db_session: AsyncSession) -> Series:
    series = Series(
        title="Batman",
        sort_title="batman",
        comicvine_id=99999,
        status=SeriesStatus.CONTINUING,
    )
    db_session.add(series)
    await db_session.flush()
    return series


@pytest.fixture()
async def test_issue(db_session: AsyncSession, test_series: Series) -> Issue:
    issue = Issue(
        series_id=test_series.id,
        issue_number=18.0,
        status=IssueStatus.WANTED,
    )
    db_session.add(issue)
    await db_session.flush()
    return issue


@pytest.fixture()
async def pending_match(db_session: AsyncSession, test_issue: Issue) -> PendingMatch:
    """Create a pending match for rejection testing."""
    pm = PendingMatch(
        issue_id=test_issue.id,
        release_title="Batman.018.2026.Digital.Zone-Empire",
        download_url="https://example.com/nzb/batman018",
        status=PendingMatchStatus.PENDING,
        confidence="high",
        match_details={},
    )
    db_session.add(pm)
    await db_session.flush()
    return pm


@pytest.fixture()
def svc() -> InterventionService:
    return InterventionService()


# ── Reject-to-blocklist tests ────────────────────────────────────────


@pytest.mark.slow
class TestRejectToBlocklist:
    """Verify rejecting a pending match adds to the blocklist."""

    async def test_reject_creates_blocklist_entry(
        self,
        db_session: AsyncSession,
        svc: InterventionService,
        pending_match: PendingMatch,
    ) -> None:
        """Rejecting a match creates a blocklist entry with reason=REJECTED."""
        await svc.reject_match(db_session, pending_match.id)

        result = await db_session.execute(select(BlocklistEntry))
        entries = list(result.scalars().all())
        assert len(entries) == 1
        assert entries[0].reason == BlocklistReason.REJECTED
        assert entries[0].release_title == pending_match.release_title

    async def test_blocklist_entry_has_correct_fields(
        self,
        db_session: AsyncSession,
        svc: InterventionService,
        pending_match: PendingMatch,
    ) -> None:
        """Blocklist entry has download_url, issue_id, indexer_id from PendingMatch."""
        await svc.reject_match(db_session, pending_match.id)

        entry = (await db_session.execute(select(BlocklistEntry))).scalar_one()
        assert entry.download_url == pending_match.download_url
        assert entry.issue_id == pending_match.issue_id
        assert entry.indexer_id == pending_match.indexer_id

    async def test_blocklist_entry_has_release_group(
        self,
        db_session: AsyncSession,
        svc: InterventionService,
        pending_match: PendingMatch,
    ) -> None:
        """Blocklist entry has release_group extracted from title."""
        await svc.reject_match(db_session, pending_match.id)

        entry = (await db_session.execute(select(BlocklistEntry))).scalar_one()
        # "Batman.018.2026.Digital.Zone-Empire" → scan_group="Zone-Empire"
        assert entry.release_group == "Zone-Empire"

    async def test_match_still_marked_rejected(
        self,
        db_session: AsyncSession,
        svc: InterventionService,
        pending_match: PendingMatch,
    ) -> None:
        """Rejecting still sets PendingMatch status to REJECTED."""
        await svc.reject_match(db_session, pending_match.id)

        pm = await db_session.get(PendingMatch, pending_match.id)
        assert pm is not None
        assert pm.status == PendingMatchStatus.REJECTED


@pytest.mark.slow
class TestRejectBlocklistEdgeCases:
    """Edge cases for reject-to-blocklist."""

    async def test_duplicate_reject_no_duplicate_blocklist(
        self,
        db_session: AsyncSession,
        svc: InterventionService,
        test_issue: Issue,
    ) -> None:
        """If same title already blocklisted, rejecting doesn't create duplicate."""
        from pullbox.services.blocklist_service import BlocklistService

        # Pre-add to blocklist
        await BlocklistService.add_entry(
            db_session,
            "Batman.018.2026.Digital.Zone-Empire",
            BlocklistReason.FAILED,
        )

        # Create and reject a match with same title
        pm = PendingMatch(
            issue_id=test_issue.id,
            release_title="Batman.018.2026.Digital.Zone-Empire",
            download_url="https://other.com/nzb/batman018",
            status=PendingMatchStatus.PENDING,
            confidence="high",
            match_details={},
        )
        db_session.add(pm)
        await db_session.flush()

        await svc.reject_match(db_session, pm.id)

        result = await db_session.execute(select(BlocklistEntry))
        entries = list(result.scalars().all())
        assert len(entries) == 1  # still just one

    async def test_reject_with_no_indexer(
        self,
        db_session: AsyncSession,
        svc: InterventionService,
        test_issue: Issue,
    ) -> None:
        """Rejecting match with no indexer creates entry with indexer_id=None."""
        pm = PendingMatch(
            issue_id=test_issue.id,
            release_title="Saga.073.2026.Minutemen",
            download_url="https://example.com/nzb/saga",
            indexer_id=None,
            status=PendingMatchStatus.PENDING,
            confidence="high",
            match_details={},
        )
        db_session.add(pm)
        await db_session.flush()

        await svc.reject_match(db_session, pm.id)

        entry = (await db_session.execute(select(BlocklistEntry))).scalar_one()
        assert entry.indexer_id is None

    async def test_non_rejected_status_does_not_blocklist(
        self,
        db_session: AsyncSession,
        test_issue: Issue,
    ) -> None:
        """Expiring a match (not rejecting) does NOT add to blocklist."""
        pm = PendingMatch(
            issue_id=test_issue.id,
            release_title="Expired.Release.001",
            download_url="https://example.com/nzb/expired",
            status=PendingMatchStatus.PENDING,
            confidence="high",
            match_details={},
        )
        db_session.add(pm)
        await db_session.flush()

        # Manually set to EXPIRED (not via reject_match)
        pm.status = PendingMatchStatus.EXPIRED
        await db_session.flush()

        result = await db_session.execute(select(BlocklistEntry))
        assert result.scalar_one_or_none() is None
