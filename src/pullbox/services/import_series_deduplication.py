"""Series-level duplicate detection for import workflows."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, NamedTuple

from sqlalchemy import ColumnElement
from sqlalchemy import func as sa_func
from sqlalchemy import or_ as sa_or
from sqlalchemy import select as sa_select

from pullbox.core.name_matcher import NameMatcher
from pullbox.core.type_semantics import series_types_compatible
from pullbox.models.import_job import (
    ImportedFile,
    ImportedSeries,
    ImportJob,
    ImportJobStatus,
    ImportSeriesStatus,
)
from pullbox.models.issue import Issue
from pullbox.models.publisher import Publisher
from pullbox.models.series import Series, SeriesType
from pullbox.schemas.import_job import ImportProgressEvent
from pullbox.services.import_matching import (
    is_same_series,
    series_type_from_import_diagnostics,
)
from pullbox.services.import_progress_runtime import (
    ScanReviewFileMatchProfile,
    ScanReviewSeriesMatchProfile,
    estimate_remaining_work_seconds,
    scan_review_completed_weight,
    scan_review_progress_pct,
    scan_review_progress_plan,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

    ProgressCallback = Callable[[ImportProgressEvent], Awaitable[None]]
    RaiseIfCancelledFunc = Callable[[AsyncSession, int], Awaitable[None]]
    LogEventFunc = Callable[..., Awaitable[None]]
    EmitProgressFunc = Callable[
        [AsyncSession, ImportJob, ImportProgressEvent, ProgressCallback],
        Awaitable[None],
    ]
    PhaseProgressFunc = Callable[[int, int, int, int], int]
    EstimateRemainingFunc = Callable[[datetime | None, int], int | None]
    JobStatsFunc = Callable[[ImportJob], dict[str, int]]


class _ExistingSeriesCandidate(NamedTuple):
    id: int
    comicvine_id: int | None
    title: str
    year_start: int | None
    series_type: SeriesType | None
    publisher_name: str | None
    issue_count: int | None
    comicvine_url: str | None


async def deduplicate_import_series(
    session: AsyncSession,
    job: ImportJob,
    *,
    raise_if_cancelled: RaiseIfCancelledFunc,
    log_event: LogEventFunc,
    emit_progress: EmitProgressFunc,
    phase_progress: PhaseProgressFunc,
    estimate_remaining_seconds: EstimateRemainingFunc,
    job_stats: JobStatsFunc,
    progress_callback: ProgressCallback | None = None,
) -> None:
    """Tag imported series rows as duplicate when they already exist in the library."""
    started_at = time.monotonic()
    persist_batch_size = 100
    last_checkpoint_at = time.monotonic()
    items_result = await session.execute(
        sa_select(ImportedSeries).where(
            ImportedSeries.import_job_id == job.id,
            ImportedSeries.status == ImportSeriesStatus.PENDING,
        )
    )
    items = items_result.scalars().all()

    requested_cv_ids = {item.cv_id for item in items if item.cv_id is not None}
    requested_titles = {
        item.raw_series_name.strip().lower() for item in items if item.raw_series_name
    }
    requested_years = {item.raw_year for item in items if item.raw_year is not None}

    existing_rows = await _load_existing_series_candidates(
        session,
        requested_cv_ids=requested_cv_ids,
        requested_titles=requested_titles,
        requested_years=requested_years,
    )

    cv_id_map: dict[int, _ExistingSeriesCandidate] = {}
    existing_list: list[_ExistingSeriesCandidate] = []
    for row in existing_rows:
        if row.comicvine_id is not None:
            cv_id_map[row.comicvine_id] = row
        existing_list.append(row)

    duplicate_count = 0
    total_items = len(items)
    progress_plan = scan_review_progress_plan(
        analysis_series_count=total_items,
        series_match_profiles=[
            ScanReviewSeriesMatchProfile(
                file_count=int(item.files_total or item.file_count or 0),
                direct_match=bool(item.cv_id),
            )
            for item in items
        ],
        file_match_profiles=[
            ScanReviewFileMatchProfile(
                file_count=int(item.files_total or item.file_count or 0),
                issue_count=item.cv_issue_count,
            )
            for item in items
            if item.has_files
        ],
    )
    for idx, item in enumerate(items):
        await raise_if_cancelled(session, job.id)
        duplicate_found = await _mark_cv_id_duplicate(
            session,
            item,
            job_id=job.id,
            cv_id_map=cv_id_map,
            log_event=log_event,
        ) or await _mark_name_year_duplicate(
            session,
            item,
            job_id=job.id,
            existing_list=existing_list,
            log_event=log_event,
        )
        if duplicate_found:
            duplicate_count += 1

        should_checkpoint = (
            idx == 0
            or (idx + 1) % persist_batch_size == 0
            or idx == total_items - 1
            or (time.monotonic() - last_checkpoint_at) >= 0.5
        )
        if should_checkpoint:
            await session.commit()
            last_checkpoint_at = time.monotonic()

        if progress_callback and should_checkpoint:
            completed_weight = scan_review_completed_weight(
                progress_plan,
                phase="analyzing",
                completed_items=idx + 1,
            )
            progress = scan_review_progress_pct(
                progress_plan,
                completed_weight=completed_weight,
            )
            job.series_duplicate = duplicate_count
            await emit_progress(
                session,
                job,
                ImportProgressEvent(
                    job_id=job.id,
                    status=ImportJobStatus.ANALYZING,
                    phase="analyzing",
                    progress=progress,
                    message=f"Analyzing {idx + 1}/{total_items}...",
                    current_series=item.raw_series_name,
                    current_series_status=item.status,
                    estimated_seconds_remaining=estimate_remaining_work_seconds(
                        job.scan_completed_at or job.scan_started_at,
                        completed_units=completed_weight,
                        total_units=progress_plan.total_weight,
                    ),
                    **job_stats(job),
                ),
                progress_callback,
            )

    job.series_duplicate = duplicate_count
    await session.flush()

    await log_event(
        session,
        job.id,
        "INFO",
        "import_dedup_completed",
        message=f"Deduplication complete: {duplicate_count} duplicates found",
        duplicate_count=duplicate_count,
        duration_ms=round((time.monotonic() - started_at) * 1000),
    )


async def _load_existing_series_candidates(
    session: AsyncSession,
    *,
    requested_cv_ids: set[int],
    requested_titles: set[str],
    requested_years: set[int],
) -> list[_ExistingSeriesCandidate]:
    existing_query = sa_select(
        Series.id,
        Series.comicvine_id,
        Series.title,
        Series.year_start,
        Series.series_type,
        Publisher.name.label("publisher_name"),
        Series.issue_count,
        Series.comicvine_url,
    ).outerjoin(Publisher, Publisher.id == Series.publisher_id)
    existing_filters: list[ColumnElement[bool]] = []
    if requested_cv_ids:
        existing_filters.append(Series.comicvine_id.in_(requested_cv_ids))
    if requested_titles:
        existing_filters.append(sa_func.lower(Series.title).in_(requested_titles))
    if requested_years:
        widened_years = {year + delta for year in requested_years for delta in (-1, 0, 1)}
        existing_filters.append(Series.year_start.in_(sorted(widened_years)))
    if existing_filters:
        existing_query = existing_query.where(sa_or(*existing_filters))

    existing_result = await session.execute(existing_query)
    return [
        _ExistingSeriesCandidate(
            id=row.id,
            comicvine_id=row.comicvine_id,
            title=row.title,
            year_start=row.year_start,
            series_type=row.series_type,
            publisher_name=row.publisher_name,
            issue_count=row.issue_count,
            comicvine_url=row.comicvine_url,
        )
        for row in existing_result.all()
    ]


async def _mark_cv_id_duplicate(
    session: AsyncSession,
    item: ImportedSeries,
    *,
    job_id: int,
    cv_id_map: dict[int, _ExistingSeriesCandidate],
    log_event: LogEventFunc,
) -> bool:
    if item.cv_id is None or item.cv_id not in cv_id_map:
        return False

    existing = cv_id_map[item.cv_id]
    item.status = ImportSeriesStatus.DUPLICATE
    item.series_id = existing.id
    _hydrate_duplicate_cv_fields(item, existing, match_score=1.0)
    item.diagnostics = {
        "kind": "duplicate_series",
        "duplicate_reason": "cv_id",
        "existing_series_id": existing.id,
        "existing_series_title": existing.title,
        "existing_series_year": existing.year_start,
        "duplicate_match_score": 1.0,
    }

    await log_event(
        session,
        job_id,
        "DEBUG",
        "import_dedup_cv_id_match",
        message=f"Duplicate: '{item.raw_series_name}' matches existing series by CV ID",
        raw_series_name=item.raw_series_name,
        cv_id=item.cv_id,
        existing_series_id=existing.id,
        existing_series_title=existing.title,
        existing_series_year=existing.year_start,
    )
    return True


async def _mark_name_year_duplicate(
    session: AsyncSession,
    item: ImportedSeries,
    *,
    job_id: int,
    existing_list: list[_ExistingSeriesCandidate],
    log_event: LogEventFunc,
) -> bool:
    candidate_series_type = series_type_from_import_diagnostics(item.diagnostics)
    for existing in existing_list:
        matched_by_name_year = is_same_series(
            item.raw_series_name,
            item.raw_year,
            candidate_series_type,
            existing.title,
            existing.year_start,
            existing.series_type,
        )
        matched_by_issue_target = (
            False
            if matched_by_name_year
            else await _exact_title_series_supports_imported_issue_targets(
                session,
                item,
                existing,
                candidate_series_type=candidate_series_type,
            )
        )
        if not matched_by_name_year and not matched_by_issue_target:
            continue

        item.status = ImportSeriesStatus.DUPLICATE
        item.series_id = existing.id
        name_match = NameMatcher().match(item.raw_series_name, existing.title)
        _hydrate_duplicate_cv_fields(item, existing, match_score=name_match.similarity)
        item.diagnostics = {
            "kind": "duplicate_series",
            "duplicate_reason": (
                "name_year" if matched_by_name_year else "exact_title_issue_target"
            ),
            "existing_series_id": existing.id,
            "existing_series_title": existing.title,
            "existing_series_year": existing.year_start,
            "duplicate_match_score": name_match.similarity,
        }

        await log_event(
            session,
            job_id,
            "DEBUG",
            "import_dedup_name_year_match",
            message=f"Duplicate: '{item.raw_series_name}' matches '{existing.title}'",
            raw_series_name=item.raw_series_name,
            raw_year=item.raw_year,
            existing_title=existing.title,
            existing_year=existing.year_start,
            existing_series_id=existing.id,
        )
        return True

    return False


async def _exact_title_series_supports_imported_issue_targets(
    session: AsyncSession,
    item: ImportedSeries,
    existing: _ExistingSeriesCandidate,
    *,
    candidate_series_type: SeriesType | None,
) -> bool:
    """Allow ongoing exact-title duplicates when file years are issue release years."""
    if not item.raw_series_name or not existing.title:
        return False
    if NameMatcher.normalize(item.raw_series_name) != NameMatcher.normalize(existing.title):
        return False
    if (
        candidate_series_type is not None
        and existing.series_type is not None
        and not series_types_compatible(candidate_series_type, existing.series_type)
    ):
        return False

    files_result = await session.execute(
        sa_select(ImportedFile.parsed_issue_number, ImportedFile.parsed_year).where(
            ImportedFile.import_series_id == item.id,
            ImportedFile.parsed_issue_number.is_not(None),
        )
    )
    requested_targets = [
        (float(row.parsed_issue_number), row.parsed_year)
        for row in files_result.all()
        if row.parsed_issue_number is not None
    ]
    if not requested_targets:
        return False

    requested_issue_numbers = {issue_number for issue_number, _year in requested_targets}
    issues_result = await session.execute(
        sa_select(Issue.issue_number, Issue.release_date).where(
            Issue.series_id == existing.id,
            Issue.issue_number.in_(requested_issue_numbers),
        )
    )
    existing_issue_by_number = {
        float(row.issue_number): row.release_date for row in issues_result.all()
    }
    if not existing_issue_by_number:
        return False

    supported_any = False
    for issue_number, parsed_year in requested_targets:
        release_date = existing_issue_by_number.get(issue_number)
        if release_date is None:
            continue
        if parsed_year is not None and abs(parsed_year - release_date.year) > 1:
            return False
        supported_any = True

    return supported_any


def _hydrate_duplicate_cv_fields(
    item: ImportedSeries,
    existing: _ExistingSeriesCandidate,
    *,
    match_score: float | None = None,
) -> None:
    """Mirror existing ComicVine metadata onto duplicate import rows."""
    if existing.comicvine_id is None:
        return

    item.cv_id = existing.comicvine_id
    item.cv_title = existing.title
    item.cv_year = existing.year_start
    item.cv_publisher = existing.publisher_name
    item.cv_issue_count = existing.issue_count
    item.cv_url = existing.comicvine_url
    if item.cv_match_score is None and match_score is not None:
        item.cv_match_score = round(match_score, 4)
