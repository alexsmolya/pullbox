"""Runtime state helpers for utility queue dispatch."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pullbox.utilities.base_executor import JobRunSummary
from pullbox.utilities.job_queue_config import (
    DEFAULT_UTILITY_LOG_LEVEL,
    DEFAULT_UTILITY_WORKER_COUNT,
)
from pullbox.utilities.models import UtilityJob

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


@dataclass(frozen=True, slots=True)
class DispatchRuntimeState:
    """Counters and settings needed while dispatching one utility job."""

    summary: JobRunSummary
    worker_count: int
    utility_log_level: str


def apply_job_counter_snapshot(
    job: UtilityJob,
    *,
    completed: int,
    failed: int,
    skipped: int,
    warnings: int,
) -> None:
    """Copy runtime counter values onto a persisted utility job row."""
    job.completed_items = completed
    job.failed_items = failed
    job.skipped_items = skipped
    job.warning_count = warnings


def build_dispatch_runtime_state(
    *,
    job_id: str,
    job_type: str,
    current_job: UtilityJob | None,
    worker_count: int = DEFAULT_UTILITY_WORKER_COUNT,
    utility_log_level: str = DEFAULT_UTILITY_LOG_LEVEL,
) -> DispatchRuntimeState:
    """Build dispatch counters/settings from a persisted job snapshot."""
    summary = JobRunSummary()
    if current_job is not None:
        summary.completed = current_job.completed_items or 0
        summary.failed = current_job.failed_items or 0
        summary.skipped = current_job.skipped_items or 0
        summary.warnings = current_job.warning_count or 0
    summary.metadata.update(
        {
            "job_id": job_id,
            "job_type": job_type,
            "utility_log_level": utility_log_level,
        }
    )
    return DispatchRuntimeState(
        summary=summary,
        worker_count=worker_count,
        utility_log_level=utility_log_level,
    )


async def load_dispatch_runtime_state(
    session: Any,
    *,
    job_id: str,
    job_type: str,
    get_worker_count: Callable[[Any], Awaitable[int]],
    get_utility_log_level: Callable[[Any], Awaitable[str]],
) -> DispatchRuntimeState:
    """Load persisted dispatch counters and runtime settings for a started job."""
    current_job = await session.get(UtilityJob, job_id)
    if current_job is None:
        return build_dispatch_runtime_state(
            job_id=job_id,
            job_type=job_type,
            current_job=None,
        )

    return build_dispatch_runtime_state(
        job_id=job_id,
        job_type=job_type,
        current_job=current_job,
        worker_count=await get_worker_count(session),
        utility_log_level=await get_utility_log_level(session),
    )
