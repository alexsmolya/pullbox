"""Private reader resume and deliberate-completion service tests."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import pytest

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
