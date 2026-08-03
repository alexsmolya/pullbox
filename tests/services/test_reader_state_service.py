"""Private reader resume and deliberate-completion service tests."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from pullbox.models import Base
from pullbox.models.reader import IssueReaderState
from pullbox.services.reader_state_service import (
    ReaderStateValidationError,
    load_reader_state,
    update_reader_state,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_resume_moves_both_directions_without_clearing_completion(
    db_session: AsyncSession,
) -> None:
    user_id, issue_id = await _seed_user_and_issue(db_session)

    completed = await update_reader_state(
        db_session,
        user_id=user_id,
        issue_id=issue_id,
        revision="revision-a",
        page_index=4,
        page_count=5,
        completion_candidate=True,
        expected_revision="revision-a",
        expected_page_count=5,
    )
    moved_back = await update_reader_state(
        db_session,
        user_id=user_id,
        issue_id=issue_id,
        revision="revision-a",
        page_index=2,
        page_count=5,
        completion_candidate=False,
        expected_revision="revision-a",
        expected_page_count=5,
    )

    assert completed.completed_at is not None
    assert moved_back.last_page_index == 2
    assert moved_back.completed_at == completed.completed_at


@pytest.mark.asyncio
async def test_new_content_revision_resets_completion_and_resume(
    db_session: AsyncSession,
) -> None:
    user_id, issue_id = await _seed_user_and_issue(db_session)
    await update_reader_state(
        db_session,
        user_id=user_id,
        issue_id=issue_id,
        revision="revision-a",
        page_index=4,
        page_count=5,
        completion_candidate=True,
        expected_revision="revision-a",
        expected_page_count=5,
    )

    updated = await update_reader_state(
        db_session,
        user_id=user_id,
        issue_id=issue_id,
        revision="revision-b",
        page_index=0,
        page_count=6,
        completion_candidate=False,
        expected_revision="revision-b",
        expected_page_count=6,
    )

    assert updated.last_page_index == 0
    assert updated.content_revision == "revision-b"
    assert updated.completed_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("revision", "page_index", "page_count", "completion_candidate"),
    [
        ("stale", 0, 5, False),
        ("revision-a", -1, 5, False),
        ("revision-a", 5, 5, False),
        ("revision-a", 0, 4, False),
        ("revision-a", 3, 5, True),
    ],
)
async def test_invalid_or_nonfinal_completion_updates_are_rejected(
    db_session: AsyncSession,
    revision: str,
    page_index: int,
    page_count: int,
    completion_candidate: bool,
) -> None:
    user_id, issue_id = await _seed_user_and_issue(db_session)

    with pytest.raises(ReaderStateValidationError):
        await update_reader_state(
            db_session,
            user_id=user_id,
            issue_id=issue_id,
            revision=revision,
            page_index=page_index,
            page_count=page_count,
            completion_candidate=completion_candidate,
            expected_revision="revision-a",
            expected_page_count=5,
        )


@pytest.mark.asyncio
async def test_load_reader_state_is_private_to_user_and_issue(db_session: AsyncSession) -> None:
    user_id, issue_id = await _seed_user_and_issue(db_session)
    await update_reader_state(
        db_session,
        user_id=user_id,
        issue_id=issue_id,
        revision="revision-a",
        page_index=2,
        page_count=5,
        completion_candidate=False,
        expected_revision="revision-a",
        expected_page_count=5,
    )

    own = await load_reader_state(db_session, user_id=user_id, issue_id=issue_id)
    absent = await load_reader_state(db_session, user_id=user_id + 1, issue_id=issue_id)

    assert own is not None
    assert own.last_page_index == 2
    assert absent is None


@pytest.mark.asyncio
async def test_concurrent_initial_progress_writes_create_one_state_row(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'reader-state.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        user_id, issue_id = await _seed_user_and_issue(session)
        await session.commit()

    ready_count = 0
    both_initial_reads_complete = asyncio.Event()

    class CoordinatedSession:
        """Hold legacy read-before-insert writes until both observed no row."""

        def __init__(self, session: AsyncSession) -> None:
            self._session = session

        async def execute(self, statement, *args, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal ready_count
            result = await self._session.execute(statement, *args, **kwargs)
            if isinstance(statement, Select):
                ready_count += 1
                if ready_count == 2:
                    both_initial_reads_complete.set()
                await asyncio.wait_for(both_initial_reads_complete.wait(), timeout=1)
            return result

        def __getattr__(self, name: str):
            return getattr(self._session, name)

    async def save(page_index: int):  # type: ignore[no-untyped-def]
        async with session_factory() as session:
            snapshot = await update_reader_state(
                CoordinatedSession(session),  # type: ignore[arg-type]
                user_id=user_id,
                issue_id=issue_id,
                revision="revision-a",
                page_index=page_index,
                page_count=5,
                completion_candidate=False,
                expected_revision="revision-a",
                expected_page_count=5,
            )
            await session.commit()
            return snapshot

    try:
        snapshots = await asyncio.gather(save(1), save(2))
        async with session_factory() as session:
            rows = list((await session.execute(select(IssueReaderState))).scalars().all())
    finally:
        await engine.dispose()

    assert len(snapshots) == 2
    assert len(rows) == 1
    assert rows[0].last_page_index in {1, 2}


async def _seed_user_and_issue(session: AsyncSession) -> tuple[int, int]:
    from pullbox.models.issue import Issue, IssueStatus
    from pullbox.models.series import Series, SeriesStatus, SeriesType
    from pullbox.models.user import User
    from pullbox.services.auth_service import AuthService

    user = User(username="reader", password_hash=AuthService.hash_password("Test@1234"))
    series = Series(
        comicvine_id=None,
        title="Reader State Series",
        sort_title="reader state series",
        year_start=2026,
        status=SeriesStatus.CONTINUING,
        series_type=SeriesType.STANDARD,
        monitored=True,
        issue_count=1,
    )
    session.add_all([user, series])
    await session.flush()
    issue = Issue(
        series_id=series.id,
        issue_number=1,
        title="Reader State Issue",
        status=IssueStatus.OWNED,
    )
    session.add(issue)
    await session.flush()
    assert isinstance(user.created_at, datetime)
    return user.id, issue.id
