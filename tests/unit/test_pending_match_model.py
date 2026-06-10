"""Tests for the PendingMatch model — ESM Phase 2, Task 2.1.

Covers:
- Creating a PendingMatch with all required fields
- Default status is PENDING
- Unique constraint on (issue_id, download_url)
- Cascade delete when parent issue is deleted
- JSON match_details round-trip storage

Run:
    pytest tests/unit/test_pending_match_model.py -v
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from pullbox.models import Base
from pullbox.models.issue import Issue, IssueStatus, IssueType
from pullbox.models.pending_match import PendingMatch, PendingMatchStatus
from pullbox.models.series import Series, SeriesStatus, SeriesType

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
async def db_factory() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_fk(dbapi_conn: object, _rec: object) -> None:
        dbapi_conn.execute("PRAGMA foreign_keys=ON")  # type: ignore[union-attr]

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _seed_issue(
    session: AsyncSession,
    *,
    series_title: str = "Batman",
    issue_number: float = 1.0,
) -> Issue:
    """Create a series + issue, return the issue."""
    series = Series(
        comicvine_id=99900,
        title=series_title,
        sort_title=series_title,
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
        issue_number=issue_number,
        title=f"Issue #{int(issue_number)}",
        status=IssueStatus.WANTED,
        issue_type=IssueType.ISSUE,
    )
    session.add(issue)
    await session.flush()
    return issue


# ── Tests ─────────────────────────────────────────────────────────────


class TestPendingMatchModel:
    """Tests for PendingMatch ORM model."""

    @pytest.mark.asyncio
    async def test_create_pending_match(self, db_factory: async_sessionmaker[AsyncSession]) -> None:
        """PendingMatch can be created with all required fields."""
        async with db_factory() as session:
            issue = await _seed_issue(session)

            pm = PendingMatch(
                issue_id=issue.id,
                release_title="Batman 001 (2016).cbz",
                download_url="https://indexer.example.com/dl/123",
                is_torrent=False,
                file_size=100_000_000,
                confidence="high",
                match_details={"parsed_series": "Batman"},
            )
            session.add(pm)
            await session.commit()

            result = await session.get(PendingMatch, pm.id)
            assert result is not None
            assert result.issue_id == issue.id
            assert result.release_title == "Batman 001 (2016).cbz"
            assert result.download_url == "https://indexer.example.com/dl/123"
            assert result.is_torrent is False
            assert result.file_size == 100_000_000
            assert result.confidence == "high"

    @pytest.mark.asyncio
    async def test_status_defaults_to_pending(
        self, db_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """Default status is PENDING when not explicitly set."""
        async with db_factory() as session:
            issue = await _seed_issue(session)

            pm = PendingMatch(
                issue_id=issue.id,
                release_title="Batman 001.cbz",
                download_url="https://indexer.example.com/dl/456",
                confidence="medium",
            )
            session.add(pm)
            await session.commit()

            result = await session.get(PendingMatch, pm.id)
            assert result is not None
            assert result.status == PendingMatchStatus.PENDING

    @pytest.mark.asyncio
    async def test_unique_constraint_issue_url(
        self, db_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """Duplicate (issue_id, download_url) raises IntegrityError."""
        async with db_factory() as session:
            issue = await _seed_issue(session)
            url = "https://indexer.example.com/dl/789"

            pm1 = PendingMatch(
                issue_id=issue.id,
                release_title="Batman 001 v1.cbz",
                download_url=url,
                confidence="high",
            )
            session.add(pm1)
            await session.commit()

        async with db_factory() as session:
            pm2 = PendingMatch(
                issue_id=issue.id,
                release_title="Batman 001 v2.cbz",
                download_url=url,
                confidence="medium",
            )
            session.add(pm2)
            with pytest.raises(IntegrityError):
                await session.commit()

    @pytest.mark.asyncio
    async def test_cascade_delete_on_issue(
        self, db_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """Deleting an issue cascades to its pending matches."""
        async with db_factory() as session:
            issue = await _seed_issue(session)

            pm = PendingMatch(
                issue_id=issue.id,
                release_title="Batman 001.cbz",
                download_url="https://indexer.example.com/dl/cascade",
                confidence="high",
            )
            session.add(pm)
            await session.commit()
            pm_id = pm.id

        async with db_factory() as session:
            issue = (await session.execute(select(Issue).where(Issue.id == issue.id))).scalar_one()
            await session.delete(issue)
            await session.commit()

        async with db_factory() as session:
            result = await session.get(PendingMatch, pm_id)
            assert result is None

    @pytest.mark.asyncio
    async def test_match_details_json(self, db_factory: async_sessionmaker[AsyncSession]) -> None:
        """match_details stores and retrieves complex JSON correctly."""
        details = {
            "parsed_series": "Absolute Superman",
            "parsed_issue": 9.0,
            "parsed_year": 2025,
            "parsed_type": "issue",
            "series_similarity": 0.92,
            "series_match_type": "fuzzy",
            "issue_match": True,
            "year_match": True,
            "type_match": True,
            "rejection_flags": [],
            "size_warning": None,
            "indexer_name": "NZBgeek",
            "age_days": 2,
            "seeders": None,
            "leechers": None,
        }

        async with db_factory() as session:
            issue = await _seed_issue(session)

            pm = PendingMatch(
                issue_id=issue.id,
                release_title="Absolute Superman 009.cbz",
                download_url="https://indexer.example.com/dl/json",
                confidence="medium",
                match_details=details,
            )
            session.add(pm)
            await session.commit()

        async with db_factory() as session:
            result = await session.get(PendingMatch, pm.id)
            assert result is not None
            assert result.match_details == details
            assert result.match_details["parsed_series"] == "Absolute Superman"
            assert result.match_details["parsed_issue"] == 9.0
            assert result.match_details["series_similarity"] == 0.92
            assert result.match_details["rejection_flags"] == []
            assert result.match_details["size_warning"] is None
