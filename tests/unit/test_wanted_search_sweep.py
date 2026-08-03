"""Durable Search Wanted sweep contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from pullbox.models import Base
from pullbox.models.issue import Issue, IssueStatus, IssueType
from pullbox.models.pending_match import PendingMatch, PendingMatchStatus
from pullbox.models.search_log import SearchLog, SearchType
from pullbox.models.series import Series, SeriesStatus, SeriesType
from pullbox.services.wanted_search_sweep import (
    WantedSearchSweepState,
    checkpoint_wanted_search_items,
    complete_wanted_search_batch,
    create_wanted_search_sweep,
    load_wanted_search_batch,
    load_wanted_search_sweep,
    save_wanted_search_sweep,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


@pytest.fixture
async def db_factory() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _seed_sweep_issues(
    factory: async_sessionmaker[AsyncSession],
) -> tuple[int, int, int, int]:
    async with factory() as session:
        series = Series(
            comicvine_id=9901,
            title="Sweep Order",
            sort_title="sweep order",
            year_start=2026,
            status=SeriesStatus.CONTINUING,
            series_type=SeriesType.STANDARD,
            monitored=True,
            issue_count=4,
        )
        session.add(series)
        await session.flush()
        issues = [
            Issue(
                series_id=series.id,
                comicvine_id=9910 + number,
                issue_number=float(number),
                title=f"Issue #{number}",
                status=IssueStatus.WANTED,
                issue_type=IssueType.ISSUE,
            )
            for number in range(1, 5)
        ]
        session.add_all(issues)
        await session.flush()
        now = datetime.now(UTC)
        # Issue 3 has never been searched and must lead the sweep. Issue 4 is
        # excluded because it already has a pending intervention decision.
        session.add_all(
            [
                SearchLog(
                    issue_id=issues[0].id,
                    series_title=series.title,
                    issue_number=issues[0].issue_number,
                    search_type=SearchType.AUTOMATED,
                    created_at=now - timedelta(hours=1),
                ),
                SearchLog(
                    issue_id=issues[1].id,
                    series_title=series.title,
                    issue_number=issues[1].issue_number,
                    search_type=SearchType.AUTOMATED,
                    created_at=now - timedelta(days=2),
                ),
                PendingMatch(
                    issue_id=issues[3].id,
                    release_title="Sweep Order 004",
                    download_url="https://example.test/sweep-order-004",
                    confidence="medium",
                    status=PendingMatchStatus.PENDING,
                ),
            ]
        )
        await session.commit()
        return tuple(issue.id for issue in issues)  # type: ignore[return-value]


@pytest.mark.asyncio
async def test_new_sweep_snapshots_eligible_targets_in_fair_order(
    db_factory: async_sessionmaker[AsyncSession],
) -> None:
    issue_1, issue_2, issue_3, _issue_4 = await _seed_sweep_issues(db_factory)

    async with db_factory() as session:
        sweep = await create_wanted_search_sweep(
            session,
            trigger_type="manual",
            now=datetime(2026, 7, 31, 12, 0, tzinfo=UTC),
        )
        await session.commit()

    assert sweep.total_targets == 3
    assert sweep.pending_issue_ids == [issue_3, issue_2, issue_1]
    assert sweep.attempted_count == 0
    assert sweep.state == "running"


@pytest.mark.asyncio
async def test_sweep_state_round_trips_and_batch_consumes_ineligible_rows(
    db_factory: async_sessionmaker[AsyncSession],
) -> None:
    issue_1, issue_2, issue_3, _issue_4 = await _seed_sweep_issues(db_factory)
    started = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)

    async with db_factory() as session:
        sweep = WantedSearchSweepState(
            state="running",
            trigger_type="scheduled",
            started_at=started,
            total_targets=3,
            pending_issue_ids=[issue_3, issue_2, issue_1],
        )
        await save_wanted_search_sweep(session, sweep)
        issue = await session.get(Issue, issue_2)
        assert issue is not None
        issue.status = IssueStatus.OWNED
        await session.commit()

    async with db_factory() as session:
        restored = await load_wanted_search_sweep(session)
        assert restored == sweep
        batch = await load_wanted_search_batch(session, restored, limit=2)

    assert batch.issue_ids == [issue_3, issue_2]
    assert [target.issue_id for target in batch.targets] == [issue_3]
    assert batch.skipped_issue_ids == [issue_2]


def test_batch_completion_waits_then_completes_full_sweep() -> None:
    started = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
    sweep = WantedSearchSweepState(
        state="running",
        trigger_type="manual",
        started_at=started,
        total_targets=3,
        pending_issue_ids=[1, 2, 3],
    )

    waiting = complete_wanted_search_batch(
        sweep,
        issue_ids=[1, 2],
        searched_count=2,
        sent=1,
        queued=1,
        failed=0,
        now=started + timedelta(minutes=20),
    )

    assert waiting.state == "waiting"
    assert waiting.attempted_count == 2
    assert waiting.pending_issue_ids == [3]
    assert waiting.next_batch_at == started + timedelta(hours=1, minutes=20)
    assert waiting.message == "Paused between batches"

    completed = complete_wanted_search_batch(
        waiting,
        issue_ids=[3],
        searched_count=1,
        sent=0,
        queued=0,
        failed=0,
        now=started + timedelta(hours=2),
    )

    assert completed.state == "completed"
    assert completed.attempted_count == 3
    assert completed.pending_issue_ids == []
    assert completed.next_batch_at is None
    assert completed.completed_at == started + timedelta(hours=2)
    assert completed.message == "Completed"


def test_item_checkpoint_removes_only_completed_work_and_preserves_batch_state() -> None:
    started = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
    sweep = WantedSearchSweepState(
        state="running",
        trigger_type="scheduled",
        started_at=started,
        total_targets=4,
        pending_issue_ids=[1, 2, 3, 4],
    )

    checkpoint = checkpoint_wanted_search_items(
        sweep,
        issue_ids=[2, 1],
        searched_count=1,
        sent=1,
        queued=0,
        failed=0,
    )

    assert checkpoint.state == "running"
    assert checkpoint.pending_issue_ids == [3, 4]
    assert checkpoint.attempted_count == 2
    assert checkpoint.searched_count == 1
    assert checkpoint.skipped_count == 1
    assert checkpoint.sent_count == 1
    assert checkpoint.batch_number == 0


def test_item_checkpoint_rejects_unknown_or_duplicate_issue_ids() -> None:
    sweep = WantedSearchSweepState(
        state="running",
        trigger_type="scheduled",
        started_at=datetime(2026, 7, 31, 12, 0, tzinfo=UTC),
        total_targets=2,
        pending_issue_ids=[1, 2],
    )

    with pytest.raises(ValueError, match="unique pending issue IDs"):
        checkpoint_wanted_search_items(
            sweep,
            issue_ids=[1, 1],
            searched_count=2,
            sent=0,
            queued=0,
            failed=0,
        )
    with pytest.raises(ValueError, match="unique pending issue IDs"):
        checkpoint_wanted_search_items(
            sweep,
            issue_ids=[3],
            searched_count=1,
            sent=0,
            queued=0,
            failed=0,
        )
