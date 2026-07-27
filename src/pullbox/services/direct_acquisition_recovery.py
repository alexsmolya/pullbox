"""Indexed restart-recovery queries for direct acquisition attempts."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import selectinload

from pullbox.models.direct_acquisition import (
    DirectAcquisitionAttempt,
    DirectAcquisitionState,
)

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession


_RUNNABLE_STATES = (
    DirectAcquisitionState.PLANNED,
    DirectAcquisitionState.QUEUED,
    DirectAcquisitionState.RESOLVING,
    DirectAcquisitionState.DOWNLOADING,
    DirectAcquisitionState.VALIDATING,
    DirectAcquisitionState.POST_PROCESSING,
)


async def load_recoverable_acquisitions(
    session: AsyncSession,
    *,
    now: datetime,
    limit: int = 100,
) -> list[DirectAcquisitionAttempt]:
    """Load runnable attempts and due retries without resuming user-held work."""
    if not 1 <= limit <= 500:
        raise ValueError("Direct acquisition recovery limit must be between 1 and 500.")

    due_retry = and_(
        DirectAcquisitionAttempt.state == DirectAcquisitionState.RETRY_PENDING,
        or_(
            DirectAcquisitionAttempt.next_retry_at.is_(None),
            DirectAcquisitionAttempt.next_retry_at <= now,
        ),
    )
    statement = (
        select(DirectAcquisitionAttempt)
        .where(
            or_(
                DirectAcquisitionAttempt.state.in_(_RUNNABLE_STATES),
                due_retry,
            )
        )
        .options(selectinload(DirectAcquisitionAttempt.artifact_attempts))
        .order_by(DirectAcquisitionAttempt.id.asc())
        .limit(limit)
    )
    result = await session.execute(statement)
    return list(result.scalars().unique().all())
