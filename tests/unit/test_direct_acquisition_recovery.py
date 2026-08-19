"""Restart-recovery query contracts for direct acquisition attempts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from pullbox.models import Base
from pullbox.models.direct_acquisition import (
    DirectAcquisitionAttempt,
    DirectAcquisitionState,
    DirectArtifactAttempt,
    DirectArtifactHostKind,
    DirectArtifactRouteKind,
    DirectArtifactState,
)
from pullbox.models.issue import Issue, IssueStatus, IssueType
from pullbox.models.series import Series, SeriesStatus, SeriesType
from pullbox.services.direct_acquisition_recovery import (
    load_due_retry_acquisitions,
    load_recoverable_acquisitions,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db_session:
        series = Series(
            comicvine_id=993_001,
            title="Recovery Test",
            sort_title="Recovery Test",
            year_start=2026,
            status=SeriesStatus.CONTINUING,
            series_type=SeriesType.STANDARD,
            monitored=True,
            issue_count=1,
        )
        db_session.add(series)
        await db_session.flush()
        db_session.add(
            Issue(
                id=1,
                series_id=series.id,
                comicvine_id=994_001,
                issue_number=1,
                status=IssueStatus.WANTED,
                issue_type=IssueType.ISSUE,
            )
        )
        await db_session.commit()
        yield db_session
    await engine.dispose()


def _attempt(
    name: str,
    state: DirectAcquisitionState,
    *,
    next_retry_at: datetime | None = None,
) -> DirectAcquisitionAttempt:
    attempt = DirectAcquisitionAttempt(
        request_key=f"recovery:{name}",
        issue_id=1,
        provider_identity="community.getcomics",
        provider_candidate_id=name,
        state=state,
        next_retry_at=next_retry_at,
        plan_revision=1,
        plan_snapshot={"schema_version": 1, "candidate": name},
        progress_revision=1,
        progress_snapshot={"stage": state.value},
    )
    attempt.artifact_attempts = [
        DirectArtifactAttempt(
            sequence_no=0,
            artifact_identity=f"artifact-{name}",
            route_kind=DirectArtifactRouteKind.DIRECT,
            host_kind=DirectArtifactHostKind.GENERIC_HTTPS,
            state=DirectArtifactState.PLANNED,
        )
    ]
    return attempt


@pytest.mark.asyncio
async def test_recovery_loads_runnable_states_and_only_due_retries(
    session: AsyncSession,
) -> None:
    session.add_all(
        [
            _attempt("planned", DirectAcquisitionState.PLANNED),
            _attempt("queued", DirectAcquisitionState.QUEUED),
            _attempt("downloading", DirectAcquisitionState.DOWNLOADING),
            _attempt(
                "retry-due",
                DirectAcquisitionState.RETRY_PENDING,
                next_retry_at=NOW - timedelta(seconds=1),
            ),
            _attempt(
                "retry-future",
                DirectAcquisitionState.RETRY_PENDING,
                next_retry_at=NOW + timedelta(hours=1),
            ),
            _attempt("paused", DirectAcquisitionState.PAUSED),
            _attempt("intervention", DirectAcquisitionState.INTERVENTION),
            _attempt("completed", DirectAcquisitionState.COMPLETED),
        ]
    )
    await session.commit()

    attempts = await load_recoverable_acquisitions(session, now=NOW, limit=100)

    assert [attempt.provider_candidate_id for attempt in attempts] == [
        "planned",
        "queued",
        "downloading",
        "retry-due",
    ]
    assert all(len(attempt.artifact_attempts) == 1 for attempt in attempts)


@pytest.mark.asyncio
async def test_recovery_treats_retry_without_schedule_as_immediately_due(
    session: AsyncSession,
) -> None:
    session.add(_attempt("retry-unscheduled", DirectAcquisitionState.RETRY_PENDING))
    await session.commit()

    attempts = await load_recoverable_acquisitions(session, now=NOW, limit=100)

    assert [attempt.provider_candidate_id for attempt in attempts] == ["retry-unscheduled"]


@pytest.mark.asyncio
async def test_due_retry_loader_excludes_active_and_future_attempts(
    session: AsyncSession,
) -> None:
    session.add_all(
        [
            _attempt("downloading", DirectAcquisitionState.DOWNLOADING),
            _attempt(
                "retry-due",
                DirectAcquisitionState.RETRY_PENDING,
                next_retry_at=NOW - timedelta(seconds=1),
            ),
            _attempt(
                "retry-future",
                DirectAcquisitionState.RETRY_PENDING,
                next_retry_at=NOW + timedelta(hours=1),
            ),
            _attempt("failed", DirectAcquisitionState.FAILED),
        ]
    )
    await session.commit()

    attempts = await load_due_retry_acquisitions(session, now=NOW, limit=100)

    assert [attempt.provider_candidate_id for attempt in attempts] == ["retry-due"]


@pytest.mark.asyncio
async def test_recovery_limit_is_bounded_and_deterministic(session: AsyncSession) -> None:
    session.add_all(
        [
            _attempt("first", DirectAcquisitionState.QUEUED),
            _attempt("second", DirectAcquisitionState.QUEUED),
            _attempt("third", DirectAcquisitionState.QUEUED),
        ]
    )
    await session.commit()

    attempts = await load_recoverable_acquisitions(session, now=NOW, limit=2)

    assert [attempt.provider_candidate_id for attempt in attempts] == ["first", "second"]


@pytest.mark.asyncio
async def test_recovery_rejects_unbounded_or_invalid_limits(session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="between 1 and 500"):
        await load_recoverable_acquisitions(session, now=NOW, limit=0)

    with pytest.raises(ValueError, match="between 1 and 500"):
        await load_recoverable_acquisitions(session, now=NOW, limit=501)
