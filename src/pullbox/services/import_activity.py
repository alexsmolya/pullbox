"""Import activity queries shared by schedulers and background guards."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from pullbox.database import get_session_factory
from pullbox.models.import_job import ImportJob, ImportJobStatus

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


IMPORT_SCHEDULER_PROTECTION_STATUSES = frozenset(
    {
        ImportJobStatus.PENDING,
        ImportJobStatus.SCANNING,
        ImportJobStatus.PAUSING,
        ImportJobStatus.ANALYZING,
        ImportJobStatus.MATCHING,
        ImportJobStatus.FILE_MATCHING,
        ImportJobStatus.IMPORTING,
        ImportJobStatus.STALLED,
        ImportJobStatus.CANCELLING,
        ImportJobStatus.ROLLING_BACK,
    }
)


def is_missing_import_jobs_table_error(exc: BaseException) -> bool:
    """Return whether import activity cannot be checked before migrations finish."""
    return "no such table: import_jobs" in str(exc).lower()


async def has_active_import_scheduler_protection(
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> bool:
    """Return whether scheduled background jobs should defer for an import.

    Step 3 review and ordinary user-paused jobs are intentionally excluded:
    review is idle, and a user pause should allow other work to continue.
    Stalled jobs remain protected until the user resumes or cancels them.
    """
    factory = session_factory or get_session_factory()
    async with factory() as session:
        active_job_id = await session.scalar(
            select(ImportJob.id)
            .where(ImportJob.status.in_(IMPORT_SCHEDULER_PROTECTION_STATUSES))
            .limit(1)
        )
    return active_job_id is not None
