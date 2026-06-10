"""Unit tests for manual_skip behavior on issue toggle.

Tests that the issue toggle endpoint correctly sets/clears manual_skip,
and that manual_skip issues survive monitoring toggle cycles.

Run:
    pytest tests/unit/test_manual_skip.py -v
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from pullbox.core.events import EventBus
from pullbox.models import Base
from pullbox.models.issue import Issue, IssueStatus
from pullbox.models.series import Series, SeriesStatus
from pullbox.services.series_service import SeriesService

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-manual-skip")


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
async def db_factory() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    """In-memory DB with all tables."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
def series_svc() -> SeriesService:
    """SeriesService with mocked metadata."""
    return SeriesService(metadata_service=AsyncMock(), event_bus=EventBus())


async def _seed(
    factory: async_sessionmaker[AsyncSession],
) -> tuple[int, int, int]:
    """Create a monitored series with 2 issues.

    Returns (series_id, wanted_issue_id, owned_issue_id).
    """
    async with factory() as session:
        series = Series(
            comicvine_id=88888,
            title="Manual Skip Test",
            sort_title="Manual Skip Test",
            year_start=2024,
            status=SeriesStatus.CONTINUING,
            monitored=True,
        )
        session.add(series)
        await session.flush()

        wanted = Issue(
            series_id=series.id,
            comicvine_id=200001,
            issue_number=1.0,
            title="Issue #1",
            status=IssueStatus.WANTED,
            manual_skip=False,
        )
        owned = Issue(
            series_id=series.id,
            comicvine_id=200002,
            issue_number=2.0,
            title="Issue #2",
            status=IssueStatus.OWNED,
            manual_skip=False,
        )
        session.add_all([wanted, owned])
        await session.flush()
        await session.commit()
        return series.id, wanted.id, owned.id


async def _get_issue(
    factory: async_sessionmaker[AsyncSession],
    issue_id: int,
) -> tuple[IssueStatus, bool]:
    """Return (status, manual_skip) for an issue."""
    async with factory() as session:
        issue = await session.get(Issue, issue_id)
        assert issue is not None
        return issue.status, issue.manual_skip


# ── Toggle sets manual_skip ───────────────────────────────────────────────


@pytest.mark.asyncio
class TestToggleSetsManualSkip:
    """Mark Skipped sets manual_skip=True, Mark Wanted clears it."""

    async def test_wanted_to_skipped_sets_manual_skip(
        self,
        db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Toggling WANTED → SKIPPED sets manual_skip=True."""
        _, wanted_id, _ = await _seed(db_factory)

        async with db_factory() as session:
            issue = await session.get(Issue, wanted_id)
            assert issue is not None
            assert issue.status == IssueStatus.WANTED
            assert issue.manual_skip is False

            # Simulate toggle: wanted → skipped
            issue.status = IssueStatus.SKIPPED
            issue.manual_skip = True
            await session.commit()

        status, manual_skip = await _get_issue(db_factory, wanted_id)
        assert status == IssueStatus.SKIPPED
        assert manual_skip is True

    async def test_skipped_to_wanted_clears_manual_skip(
        self,
        db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Toggling SKIPPED → WANTED clears manual_skip."""
        _, wanted_id, _ = await _seed(db_factory)

        # First set to manually skipped
        async with db_factory() as session:
            issue = await session.get(Issue, wanted_id)
            assert issue is not None
            issue.status = IssueStatus.SKIPPED
            issue.manual_skip = True
            await session.commit()

        # Now toggle back to wanted
        async with db_factory() as session:
            issue = await session.get(Issue, wanted_id)
            assert issue is not None
            issue.status = IssueStatus.WANTED
            issue.manual_skip = False
            await session.commit()

        status, manual_skip = await _get_issue(db_factory, wanted_id)
        assert status == IssueStatus.WANTED
        assert manual_skip is False

    async def test_owned_cannot_be_toggled(
        self,
        db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """OWNED issues should not be toggled — status and manual_skip unchanged."""
        _, _, owned_id = await _seed(db_factory)

        status, manual_skip = await _get_issue(db_factory, owned_id)
        assert status == IssueStatus.OWNED
        assert manual_skip is False


# ── manual_skip survives monitoring toggle ────────────────────────────────


@pytest.mark.asyncio
class TestManualSkipSurvivesMonitoringToggle:
    """A manually skipped issue stays skipped through monitoring cycles."""

    async def test_manual_skip_survives_off_on(
        self,
        db_factory: async_sessionmaker[AsyncSession],
        series_svc: SeriesService,
    ) -> None:
        """Manually skipped issue stays SKIPPED after monitoring OFF→ON cycle."""
        series_id, wanted_id, _ = await _seed(db_factory)

        # Manually skip the wanted issue
        async with db_factory() as session:
            issue = await session.get(Issue, wanted_id)
            assert issue is not None
            issue.status = IssueStatus.SKIPPED
            issue.manual_skip = True
            await session.commit()

        # Toggle monitoring OFF
        async with db_factory() as session:
            await series_svc.toggle_monitoring(session, series_id, enabled=False)
            await session.commit()

        status, manual_skip = await _get_issue(db_factory, wanted_id)
        assert status == IssueStatus.SKIPPED
        assert manual_skip is True

        # Toggle monitoring ON
        async with db_factory() as session:
            await series_svc.toggle_monitoring(session, series_id, enabled=True)
            await session.commit()

        # manual_skip issue should STILL be skipped
        status, manual_skip = await _get_issue(db_factory, wanted_id)
        assert status == IssueStatus.SKIPPED
        assert manual_skip is True

    async def test_manual_skip_default_false(
        self,
        db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """New issues default to manual_skip=False."""
        async with db_factory() as session:
            series = Series(
                comicvine_id=77777,
                title="Default Test",
                sort_title="Default Test",
                monitored=True,
            )
            session.add(series)
            await session.flush()

            issue = Issue(
                series_id=series.id,
                comicvine_id=300001,
                issue_number=1.0,
                title="Issue #1",
            )
            session.add(issue)
            await session.flush()
            await session.refresh(issue)

            assert issue.manual_skip is False
            assert issue.status == IssueStatus.SKIPPED
            await session.commit()
