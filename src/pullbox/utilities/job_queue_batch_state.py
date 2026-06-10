"""Batch item state helpers for utility queue dispatch."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import update

from pullbox.utilities.job_queue_state import transition_job_state
from pullbox.utilities.models import ItemState, JobState, UtilityJob, UtilityJobItem

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable

    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class BatchCheckpoint:
    """Control decision and refreshed settings before dispatching a batch."""

    should_continue: bool
    utility_log_level: str


async def prepare_batch_checkpoint(
    session: Any,
    *,
    job_id: str,
    summary: Any,
    get_utility_log_level: Callable[[Any], Awaitable[str]],
) -> BatchCheckpoint:
    """Refresh runtime settings and honor pause/cancel state before a batch."""
    current_job = await session.get(UtilityJob, job_id)
    utility_log_level = await get_utility_log_level(session)
    summary.metadata["utility_log_level"] = utility_log_level

    if current_job and current_job.state == JobState.PAUSING:
        transition_job_state(current_job, JobState.PAUSED)
        await session.commit()
        return BatchCheckpoint(
            should_continue=False,
            utility_log_level=utility_log_level,
        )
    if current_job and current_job.state in (
        JobState.CANCELLING,
        JobState.CANCELLED,
    ):
        return BatchCheckpoint(
            should_continue=False,
            utility_log_level=utility_log_level,
        )

    return BatchCheckpoint(
        should_continue=True,
        utility_log_level=utility_log_level,
    )


async def mark_batch_items_in_progress(
    session: AsyncSession,
    *,
    item_ids: Iterable[str],
    started_at: str,
) -> None:
    """Mark a batch of pending job items as leased to workers."""
    await session.execute(
        update(UtilityJobItem)
        .where(UtilityJobItem.id.in_(list(item_ids)))
        .values(
            state=ItemState.IN_PROGRESS,
            started_at=started_at,
            completed_at=None,
            worker_id=None,
        )
    )


async def lease_dispatch_batch(
    session: AsyncSession,
    *,
    pending_items: list[UtilityJobItem],
    batch_start: int,
    batch_size: int,
    started_at: str,
) -> list[UtilityJobItem]:
    """Mark and return the next pending item slice leased to workers."""
    batch_items = pending_items[batch_start : batch_start + batch_size]
    await mark_batch_items_in_progress(
        session,
        item_ids=[item.id for item in batch_items],
        started_at=started_at,
    )
    await session.commit()
    return batch_items
