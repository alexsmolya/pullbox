"""Import file selection and issue-resolution helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select as sa_select
from sqlalchemy.orm import joinedload

from pullbox.models.import_job import ImportedFile, ImportedFileStatus, ImportedSeries
from pullbox.models.issue import Issue
from pullbox.models.series import Series

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def load_importable_files(
    session: AsyncSession,
    item: ImportedSeries,
    *,
    duplicate_mode: bool = False,
) -> list[ImportedFile]:
    """Load files eligible for import for a reviewed series bucket."""
    file_filters = [
        ImportedFile.import_series_id == item.id,
        ImportedFile.status.in_([ImportedFileStatus.MATCHED, ImportedFileStatus.CONFIRMED]),
    ]
    if duplicate_mode:
        file_filters.append(ImportedFile.include_in_import.is_(True))

    files_result = await session.execute(sa_select(ImportedFile).where(*file_filters))
    importable_files = list(files_result.scalars().all())

    if not duplicate_mode:
        conflict_result = await session.execute(
            sa_select(ImportedFile).where(
                ImportedFile.import_series_id == item.id,
                ImportedFile.status == ImportedFileStatus.CONFLICT,
                ImportedFile.is_preferred.is_(True),
            )
        )
        importable_files.extend(conflict_result.scalars().all())

    return importable_files


async def load_issue_lookup_for_series(
    session: AsyncSession,
    series_id: int | None,
) -> tuple[dict[int, Issue], dict[float, Issue]]:
    """Build ComicVine-ID and issue-number lookup maps for a library series."""
    if series_id is None:
        return {}, {}

    issues_result = await session.execute(
        sa_select(Issue)
        .options(joinedload(Issue.series).joinedload(Series.publisher))
        .where(Issue.series_id == series_id)
        .execution_options(populate_existing=True)
    )
    issues = issues_result.scalars().all()

    cv_id_to_issue: dict[int, Issue] = {}
    number_to_issue: dict[float, Issue] = {}
    for issue in issues:
        if issue.comicvine_id is not None:
            cv_id_to_issue[issue.comicvine_id] = issue
        number_to_issue[issue.issue_number] = issue
    return cv_id_to_issue, number_to_issue


async def resolve_import_file_issue(
    session: AsyncSession,
    imp_file: ImportedFile,
    *,
    cv_id_to_issue: dict[int, Issue],
    number_to_issue: dict[float, Issue],
) -> Issue | None:
    """Resolve a pre-import file match to a persisted library issue."""
    if imp_file.matched_issue_id is not None:
        resolved_issue = await session.get(Issue, imp_file.matched_issue_id)
        if resolved_issue is not None:
            return resolved_issue

    if imp_file.matched_issue_cv_id:
        resolved_issue = cv_id_to_issue.get(imp_file.matched_issue_cv_id)
        if resolved_issue is not None:
            return resolved_issue

    if imp_file.comicvine_issue_id:
        resolved_issue = cv_id_to_issue.get(imp_file.comicvine_issue_id)
        if resolved_issue is not None:
            return resolved_issue

    if imp_file.parsed_issue_number is not None:
        return number_to_issue.get(imp_file.parsed_issue_number)

    return None
