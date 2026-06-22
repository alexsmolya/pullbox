"""Context loading for import Step 5 results."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import case, func, select

from pullbox.models.import_job import (
    ImportedFile,
    ImportedFileStatus,
    ImportedSeries,
    ImportJob,
    ImportSeriesStatus,
)
from pullbox.models.series import IssueCatalogState, Series
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


async def _load_catalog_sync_series(session: AsyncSession, job_id: int) -> list[Series]:
    """Return imported series whose full ComicVine issue catalog is not complete yet."""
    state_rank = {
        IssueCatalogState.FAILED: 0,
        IssueCatalogState.PARTIAL: 1,
        IssueCatalogState.HYDRATING: 2,
    }
    result = await session.execute(
        select(Series)
        .join(ImportedSeries, ImportedSeries.series_id == Series.id)
        .where(
            ImportedSeries.import_job_id == job_id,
            ImportedSeries.status == ImportSeriesStatus.IMPORTED,
            Series.issue_catalog_state.in_(
                [
                    IssueCatalogState.HYDRATING,
                    IssueCatalogState.PARTIAL,
                    IssueCatalogState.FAILED,
                ]
            ),
        )
        .order_by(
            case(
                *[
                    (Series.issue_catalog_state == state, rank)
                    for state, rank in state_rank.items()
                ],
                else_=99,
            ),
            Series.sort_title.asc(),
        )
    )
    return list(result.unique().scalars().all())


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
    catalog_sync_series = await _load_catalog_sync_series(session, job_id)
    catalog_sync_failed_count = sum(
        1
        for series in catalog_sync_series
        if series.issue_catalog_state == IssueCatalogState.FAILED
    )
    catalog_sync_pending_count = len(catalog_sync_series) - catalog_sync_failed_count

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
        "catalog_sync_pending_count": catalog_sync_pending_count,
        "catalog_sync_failed_count": catalog_sync_failed_count,
        "catalog_sync_attention_count": len(catalog_sync_series),
        "catalog_sync_series": catalog_sync_series,
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
