"""Import rollback review-state helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select as sa_select

from pullbox.models.import_job import (
    ImportedFile,
    ImportedFileStatus,
    ImportedSeries,
    ImportSeriesStatus,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def restore_review_state_after_rollback(session: AsyncSession, job_id: int) -> None:
    """Restore imported rows to their pre-import review states after rollback."""
    series_result = await session.execute(
        sa_select(ImportedSeries).where(ImportedSeries.import_job_id == job_id)
    )
    series_items = list(series_result.scalars().all())

    files_result = await session.execute(
        sa_select(ImportedFile).where(ImportedFile.import_job_id == job_id)
    )
    imported_files = list(files_result.scalars().all())
    orphan_recovery_series_ids = {
        imp_file.import_series_id
        for imp_file in imported_files
        if dict(imp_file.diagnostics or {}).get("kind") == "orphan_recovery"
    }

    for series_item in series_items:
        if series_item.status in {
            ImportSeriesStatus.IMPORTED,
            ImportSeriesStatus.FAILED,
            ImportSeriesStatus.CONFIRMED,
            ImportSeriesStatus.IMPORTING,
        }:
            series_item.status = (
                ImportSeriesStatus.RECOVERY_PENDING
                if series_item.id in orphan_recovery_series_ids
                else ImportSeriesStatus.MATCHED
            )
            series_item.series_id = None
            series_item.error_message = None
            series_item.files_imported = 0
            series_item.files_failed = 0

    for imp_file in imported_files:
        diagnostics = dict(imp_file.diagnostics or {})
        if imp_file.status not in {
            ImportedFileStatus.IMPORTED,
            ImportedFileStatus.FAILED,
            ImportedFileStatus.CONFIRMED,
            ImportedFileStatus.SKIPPED,
        }:
            continue

        if diagnostics.get("kind") == "orphan_recovery":
            if diagnostics.get("resolution") == "skipped":
                imp_file.status = ImportedFileStatus.SKIPPED
                imp_file.include_in_import = False
            elif imp_file.matched_issue_id is not None or imp_file.matched_issue_cv_id is not None:
                imp_file.status = ImportedFileStatus.MATCHED
                imp_file.include_in_import = False
            else:
                imp_file.status = ImportedFileStatus.NO_MATCH
                imp_file.include_in_import = False
        elif imp_file.conflict_group_id is not None:
            imp_file.status = ImportedFileStatus.CONFLICT
            imp_file.include_in_import = False
        elif diagnostics.get("target_state") == "already_owned":
            imp_file.status = ImportedFileStatus.ALREADY_OWNED
            imp_file.include_in_import = False
        elif imp_file.matched_issue_id is not None or imp_file.matched_issue_cv_id is not None:
            imp_file.status = ImportedFileStatus.MATCHED
            imp_file.include_in_import = False
        else:
            imp_file.status = ImportedFileStatus.NO_MATCH
            imp_file.include_in_import = False
        imp_file.library_file_id = None
        imp_file.error_message = None
