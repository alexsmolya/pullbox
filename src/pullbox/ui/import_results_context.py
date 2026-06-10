"""Context loading for import Step 5 results."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select

from pullbox.models.import_job import (
    ImportedFile,
    ImportedFileStatus,
    ImportedSeries,
    ImportJob,
    ImportSeriesStatus,
)
from pullbox.services.import_workflow_state import import_control_state_for_job

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def _count_series_status(
    session: AsyncSession,
    job_id: int,
    status: ImportSeriesStatus,
) -> int:
    return int(
        (
            await session.execute(
                select(func.count(ImportedSeries.id)).where(
                    ImportedSeries.import_job_id == job_id,
                    ImportedSeries.status == status,
                )
            )
        ).scalar_one()
        or 0
    )


async def _load_file_status_counts(session: AsyncSession, job_id: int) -> dict[str, int]:
    file_status_counts: dict[str, int] = {}
    for file_status in ImportedFileStatus:
        count = int(
            (
                await session.execute(
                    select(func.count(ImportedFile.id)).where(
                        ImportedFile.import_job_id == job_id,
                        ImportedFile.status == file_status,
                    )
                )
            ).scalar_one()
            or 0
        )
        if count > 0:
            file_status_counts[file_status.value] = count
    return file_status_counts


async def _load_files_for_status(
    session: AsyncSession,
    job_id: int,
    status: ImportedFileStatus,
) -> list[ImportedFile]:
    result = await session.execute(
        select(ImportedFile).where(
            ImportedFile.import_job_id == job_id,
            ImportedFile.status == status,
        )
    )
    return list(result.scalars().all())


async def _orphaned_file_no_match_count(session: AsyncSession, job_id: int) -> int:
    return int(
        (
            await session.execute(
                select(func.count(ImportedFile.id))
                .join(ImportedSeries, ImportedFile.import_series_id == ImportedSeries.id)
                .where(
                    ImportedFile.import_job_id == job_id,
                    ImportedFile.status == ImportedFileStatus.NO_MATCH,
                    ImportedSeries.status.in_(
                        [
                            ImportSeriesStatus.NO_MATCH,
                            ImportSeriesStatus.RECOVERY_PENDING,
                        ]
                    ),
                )
            )
        ).scalar_one()
        or 0
    )


async def load_import_results_context(
    session: AsyncSession,
    job: ImportJob,
) -> dict[str, object]:
    """Load aggregate counts and detail rows for the Step 5 results template."""
    job_id = int(job.id)
    imported_count = await _count_series_status(session, job_id, ImportSeriesStatus.IMPORTED)
    failed_count = await _count_series_status(session, job_id, ImportSeriesStatus.FAILED)
    duplicate_count = await _count_series_status(session, job_id, ImportSeriesStatus.DUPLICATE)
    no_match_count = await _count_series_status(session, job_id, ImportSeriesStatus.NO_MATCH)
    recovery_pending_count = await _count_series_status(
        session,
        job_id,
        ImportSeriesStatus.RECOVERY_PENDING,
    )
    imported_issue_recovery_count = int(
        (
            await session.execute(
                select(func.count(ImportedSeries.id)).where(
                    ImportedSeries.import_job_id == job_id,
                    ImportedSeries.status == ImportSeriesStatus.IMPORTED,
                    select(ImportedFile.id)
                    .where(
                        ImportedFile.import_series_id == ImportedSeries.id,
                        ImportedFile.status == ImportedFileStatus.NO_MATCH,
                    )
                    .exists(),
                )
            )
        ).scalar_one()
        or 0
    )
    unmatched_queue_count = no_match_count + recovery_pending_count + imported_issue_recovery_count

    failed_series: list[ImportedSeries] = []
    if failed_count > 0:
        result = await session.execute(
            select(ImportedSeries).where(
                ImportedSeries.import_job_id == job_id,
                ImportedSeries.status == ImportSeriesStatus.FAILED,
            )
        )
        failed_series = list(result.scalars().all())

    file_status_counts = await _load_file_status_counts(session, job_id)
    files_imported = max(
        file_status_counts.get(ImportedFileStatus.IMPORTED.value, 0),
        job.total_files_imported or 0,
    )
    files_matched = max(
        file_status_counts.get(ImportedFileStatus.MATCHED.value, 0),
        job.total_files_matched or 0,
    )
    files_duplicate = max(
        file_status_counts.get(ImportedFileStatus.DUPLICATE_FILE.value, 0),
        job.total_files_duplicate or 0,
    )
    files_already_owned = max(
        file_status_counts.get(ImportedFileStatus.ALREADY_OWNED.value, 0),
        job.total_files_already_owned or 0,
    )
    files_conflict = max(
        file_status_counts.get(ImportedFileStatus.CONFLICT.value, 0),
        job.total_files_conflict or 0,
    )
    files_no_match = max(
        file_status_counts.get(ImportedFileStatus.NO_MATCH.value, 0),
        job.total_files_no_match or 0,
    )
    files_failed = max(
        file_status_counts.get(ImportedFileStatus.FAILED.value, 0),
        job.total_files_failed or 0,
    )
    files_safety_blocked = file_status_counts.get(
        ImportedFileStatus.SAFETY_BLOCKED.value,
        0,
    )
    files_total = sum(file_status_counts.values())
    orphaned_file_no_match_count = await _orphaned_file_no_match_count(session, job_id)
    identified_series_file_no_match_count = max(
        files_no_match - orphaned_file_no_match_count,
        0,
    )

    return {
        "can_rollback": bool(import_control_state_for_job(job).get("can_rollback")),
        "imported_count": imported_count,
        "failed_count": failed_count,
        "duplicate_count": duplicate_count,
        "no_match_count": no_match_count,
        "unmatched_queue_count": unmatched_queue_count,
        "failed_series": failed_series,
        "files_total": files_total,
        "files_imported": files_imported,
        "files_matched": files_matched,
        "files_duplicate": files_duplicate,
        "files_already_owned": files_already_owned,
        "files_conflict": files_conflict,
        "files_no_match": files_no_match,
        "orphaned_file_no_match_count": orphaned_file_no_match_count,
        "identified_series_file_no_match_count": identified_series_file_no_match_count,
        "files_failed": files_failed,
        "failed_files": (
            await _load_files_for_status(session, job_id, ImportedFileStatus.FAILED)
            if files_failed > 0
            else []
        ),
        "files_safety_blocked": files_safety_blocked,
        "safety_blocked_files": (
            await _load_files_for_status(
                session,
                job_id,
                ImportedFileStatus.SAFETY_BLOCKED,
            )
            if files_safety_blocked > 0
            else []
        ),
    }
