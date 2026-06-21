"""Metadata background tasks — syncs new issues and refreshes stale metadata.

Two scheduled tasks:
- ``sync_new_issues`` (daily cron) — fetches issue lists for
  ComicVine-backed series, creates new Issue records, and refreshes stale
  series metadata changes (status, description, publisher).  When new issues
  are set to WANTED by monitoring criteria, a one-shot search is scheduled.
- ``refresh_metadata`` (cron, default 03:00) — re-fetches series metadata
  when it exceeds the configured staleness threshold.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import func, or_, select

from pullbox.config import PullboxSettings, get_settings
from pullbox.core.log_deduper import log_deduped_warning

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from pullbox.core.comicvine_key import get_comicvine_api_key
from pullbox.core.scheduler import get_scheduler
from pullbox.database import get_session_factory
from pullbox.models.issue import Issue, IssueStatus
from pullbox.models.series import IssueCatalogState, Series, SeriesStatus
from pullbox.providers.metadata.comicvine import ComicVineProvider
from pullbox.services.metadata_service import MetadataService

logger = structlog.get_logger(__name__)

_RECENT_ISSUE_SYNC_LIMIT = 100
_STANDARD_ISSUE_CHECK_INTERVAL = timedelta(hours=24)
_ENDED_MONITORED_ISSUE_CHECK_INTERVAL = timedelta(days=14)
_ENDED_UNMONITORED_ISSUE_CHECK_INTERVAL = timedelta(days=30)


async def _create_metadata_service(
    api_key: str,
    settings: PullboxSettings,
    session: AsyncSession,
) -> MetadataService:
    """Build a ComicVineProvider + MetadataService from an API key and settings."""
    from pullbox.services.cover_resolver import resolve_covers_dir

    provider = ComicVineProvider(
        api_key=api_key,
        rate_limit=settings.comicvine_rate_limit,
    )
    covers_dir = await resolve_covers_dir(session)
    return MetadataService(
        provider,
        covers_dir=covers_dir,
        refresh_days=settings.metadata_refresh_days,
    )


@dataclass
class _SeriesSnapshot:
    """Snapshot of series fields for change detection."""

    status: str
    description: str | None
    publisher_id: int | None


def _take_snapshot(series: Series) -> _SeriesSnapshot:
    """Capture current series metadata for later comparison."""
    return _SeriesSnapshot(
        status=str(series.status),
        description=series.description,
        publisher_id=series.publisher_id,
    )


def _detect_changes(
    series: Series,
    before: _SeriesSnapshot,
    log: structlog.stdlib.BoundLogger,
) -> tuple[bool, bool]:
    """Compare series against its snapshot. Returns (status_changed, metadata_changed)."""
    status_changed = False
    metadata_changed = False

    current_status = str(series.status)
    if current_status != before.status:
        status_changed = True
        log.info(
            "series_status_changed",
            old_status=before.status,
            new_status=current_status,
        )

    if series.description != before.description:
        metadata_changed = True
        log.debug("series_description_updated")

    if series.publisher_id != before.publisher_id:
        metadata_changed = True
        log.debug("series_publisher_updated")

    return status_changed, metadata_changed


def _metadata_refresh_due(series: Series, refresh_days: int) -> bool:
    """Return True when series-level metadata is missing or stale."""
    refreshed = series.metadata_last_refreshed
    if refreshed is None:
        return True
    if refreshed.tzinfo is None:
        refreshed = refreshed.replace(tzinfo=UTC)
    return (datetime.now(UTC) - refreshed).days >= refresh_days


def _metadata_refresh_days(settings: PullboxSettings) -> int:
    """Read metadata refresh days defensively for tests and runtime overrides."""
    try:
        return int(settings.metadata_refresh_days)
    except (TypeError, ValueError):
        return 30


def _can_bootstrap_complete_catalog(series: Series, local_issue_count: int) -> bool:
    """Return True when a legacy complete catalog can safely start with recent sync."""
    provider_issue_count = int(series.issue_count or 0)
    return (
        series.issue_catalog_state == IssueCatalogState.COMPLETE
        and series.issue_catalog_last_synced_at is None
        and provider_issue_count > 0
        and local_issue_count >= provider_issue_count
    )


def _issue_catalog_full_sync_due(
    series: Series,
    refresh_days: int,
    *,
    local_issue_count: int = 0,
) -> bool:
    """Return True when scheduled issue sync should fetch the full issue list."""
    if refresh_days <= 0:
        return True
    if series.issue_catalog_state != IssueCatalogState.COMPLETE:
        return True
    synced = series.issue_catalog_last_synced_at
    if synced is None:
        return not _can_bootstrap_complete_catalog(series, local_issue_count)
    if synced.tzinfo is None:
        synced = synced.replace(tzinfo=UTC)
    return (datetime.now(UTC) - synced).days >= refresh_days


def _issue_check_interval_for_series(series: Series) -> timedelta:
    """Return the normal issue-check cadence for a complete catalog."""
    if series.status == SeriesStatus.ENDED:
        if series.monitored:
            return _ENDED_MONITORED_ISSUE_CHECK_INTERVAL
        return _ENDED_UNMONITORED_ISSUE_CHECK_INTERVAL
    return _STANDARD_ISSUE_CHECK_INTERVAL


def _issue_catalog_check_due(series: Series, *, now: datetime | None = None) -> bool:
    """Return True when a series should spend a ComicVine request on issue checks."""
    if series.issue_catalog_state != IssueCatalogState.COMPLETE:
        return True

    checked = series.issue_catalog_last_checked_at
    if checked is None:
        return True
    if checked.tzinfo is None:
        checked = checked.replace(tzinfo=UTC)

    current_time = now or datetime.now(UTC)
    interval = _issue_check_interval_for_series(series)
    return current_time - checked >= interval


async def _sync_issue_catalog_for_series(
    metadata_svc: MetadataService,
    session: AsyncSession,
    series: Series,
    *,
    full_refresh_days: int,
    local_issue_count: int = 0,
) -> tuple[list[Issue], str]:
    """Sync one series' issue catalog using full or recent ComicVine issue fetches."""
    bootstrap_complete_catalog = _can_bootstrap_complete_catalog(series, local_issue_count)
    checked_at = datetime.now(UTC)
    if _issue_catalog_full_sync_due(
        series,
        full_refresh_days,
        local_issue_count=local_issue_count,
    ):
        created = await metadata_svc.fetch_issues_for_series(session, series.id)
        mode = "full"
        series.issue_catalog_last_synced_at = checked_at
        series.issue_catalog_last_checked_at = checked_at
    else:
        created = await metadata_svc.fetch_recent_issues_for_series(
            session,
            series.id,
            limit=_RECENT_ISSUE_SYNC_LIMIT,
        )
        mode = "recent"
        series.issue_catalog_last_checked_at = checked_at
        if bootstrap_complete_catalog:
            series.issue_catalog_last_synced_at = checked_at

    series.issue_catalog_state = IssueCatalogState.COMPLETE
    series.issue_catalog_error = None
    return created, mode


async def sync_new_issues() -> None:
    """Fetch issue lists from ComicVine for all ComicVine-backed series.

    Also refreshes stale series metadata and detects status/field changes.
    """
    settings = get_settings()
    factory = get_session_factory()

    async with factory() as session:
        api_key = await get_comicvine_api_key(session)
        if not api_key:
            log_deduped_warning(
                logger,
                "sync_new_issues_missing_comicvine_key",
                key="sync_new_issues_missing_comicvine_key",
                action_required="Configure a ComicVine API key to enable issue sync.",
            )
            return

        metadata_svc = await _create_metadata_service(api_key, settings, session)
        metadata_refresh_days = _metadata_refresh_days(settings)
        try:
            # Process ALL series — sync_new_issues is monitoring-flag-independent.
            # Load stable IDs up front so we can commit per-series without relying
            # on long-lived ORM instances that would otherwise keep one write
            # transaction open for the entire run.
            result = await session.execute(select(Series.id).where(Series.comicvine_id.isnot(None)))
            series_ids = list(result.scalars().all())

            if not series_ids:
                logger.debug("sync_new_issues_skip", reason="no series")
                return

            local_counts_result = await session.execute(
                select(Issue.series_id, func.count(Issue.id))
                .where(Issue.series_id.in_(series_ids))
                .group_by(Issue.series_id)
            )
            local_issue_counts = {
                int(series_id): int(count)
                for series_id, count in local_counts_result.all()
                if series_id is not None
            }

            new_issues = 0
            status_changes = 0
            metadata_updates = 0
            failed = 0
            full_issue_syncs = 0
            recent_issue_syncs = 0
            skipped_issue_syncs = 0
            series_to_search: list[int] = []

            for series_id in series_ids:
                series = await session.get(Series, series_id)
                if series is None:
                    continue

                log = logger.bind(series_id=series.id, title=series.title)
                try:
                    # Snapshot current metadata before refresh
                    before = _take_snapshot(series)

                    # Refresh series metadata only when stale. Issue-list sync
                    # below still runs every pass so new issue discovery is
                    # unchanged.
                    if series.comicvine_id and _metadata_refresh_due(
                        series,
                        metadata_refresh_days,
                    ):
                        await metadata_svc.fetch_series(session, series.comicvine_id)
                        # Re-fetch the series to see updated fields
                        await session.refresh(series)

                        sc, mc = _detect_changes(series, before, log)
                        if sc:
                            status_changes += 1
                        if mc:
                            metadata_updates += 1

                    # Fetch new issues. Complete catalogs use a one-page recent
                    # sync between periodic full refreshes; incomplete/stale
                    # catalogs still fetch the full list.
                    if not _issue_catalog_check_due(series):
                        skipped_issue_syncs += 1
                        log.debug(
                            "sync_new_issues_issue_check_skipped",
                            issue_catalog_last_checked_at=(
                                series.issue_catalog_last_checked_at.isoformat()
                                if series.issue_catalog_last_checked_at
                                else None
                            ),
                            issue_check_interval_seconds=(
                                _issue_check_interval_for_series(series).total_seconds()
                            ),
                        )
                        await session.commit()
                        continue

                    created, issue_sync_mode = await _sync_issue_catalog_for_series(
                        metadata_svc,
                        session,
                        series,
                        full_refresh_days=metadata_refresh_days,
                        local_issue_count=local_issue_counts.get(series.id, 0),
                    )
                    if issue_sync_mode == "full":
                        full_issue_syncs += 1
                    else:
                        recent_issue_syncs += 1
                    new_issues += len(created)

                    # New issues on monitored series → WANTED, unmonitored → SKIPPED (default)
                    if created and series.monitored:
                        new_wanted_ids: list[int] = []
                        for issue in created:
                            if issue.status == IssueStatus.SKIPPED:
                                issue.status = IssueStatus.WANTED
                                new_wanted_ids.append(issue.id)

                        if new_wanted_ids:
                            series_to_search.append(series.id)
                            log.debug(
                                "new_issues_marked_wanted",
                                new_wanted=len(new_wanted_ids),
                            )

                    # Release SQLite's writer lock after each series so other
                    # background tasks, including scheduler stat persistence,
                    # are not blocked behind one long metadata sync.
                    await session.commit()

                except Exception:
                    await session.rollback()
                    failed += 1
                    log.exception("sync_new_issues_series_failed")
            logger.info(
                "sync_new_issues_complete",
                new_issues=new_issues,
                status_changes=status_changes,
                metadata_updates=metadata_updates,
                series_checked=len(series_ids),
                full_issue_syncs=full_issue_syncs,
                recent_issue_syncs=recent_issue_syncs,
                skipped_issue_syncs=skipped_issue_syncs,
                failed=failed,
            )

            # Schedule one-shot searches for series with new wanted issues
            if series_to_search:
                from pullbox.tasks.search_task import search_series_issues

                scheduler = get_scheduler()
                for sid in series_to_search:
                    job_id = f"search_new_{sid}_{int(time.time())}"
                    scheduler._scheduler.add_job(
                        search_series_issues,
                        trigger="date",
                        args=[sid],
                        id=job_id,
                        misfire_grace_time=300,
                    )
                logger.info(
                    "scheduled_search_for_new_issues",
                    series_count=len(series_to_search),
                    series_ids=series_to_search,
                )
        except Exception:
            await session.rollback()
            raise


async def refresh_metadata() -> None:
    """Re-fetch metadata for series that are stale or have never been refreshed."""
    settings = get_settings()
    factory = get_session_factory()

    async with factory() as session:
        api_key = await get_comicvine_api_key(session)
        if not api_key:
            log_deduped_warning(
                logger,
                "refresh_metadata_missing_comicvine_key",
                key="refresh_metadata_missing_comicvine_key",
                action_required="Configure a ComicVine API key to enable metadata refresh.",
            )
            return

        metadata_svc = await _create_metadata_service(api_key, settings, session)
        try:
            cutoff = datetime.now(UTC) - timedelta(days=settings.metadata_refresh_days)

            result = await session.execute(
                select(Series.id).where(
                    Series.monitored.is_(True),
                    or_(
                        Series.metadata_last_refreshed.is_(None),
                        Series.metadata_last_refreshed < cutoff,
                    ),
                )
            )
            stale_ids = list(result.scalars().all())

            if not stale_ids:
                logger.debug("refresh_metadata_skip", reason="no stale series")
                return

            refreshed = 0
            failed = 0
            for series_id in stale_ids:
                series = await session.get(Series, series_id)
                if series is None:
                    continue
                series_title = series.title
                try:
                    await metadata_svc.refresh_series(session, series.id)
                    refreshed += 1
                    # Release SQLite's writer lock after each series refresh so
                    # this nightly job doesn't monopolize the DB for the entire batch.
                    await session.commit()
                except Exception:
                    await session.rollback()
                    failed += 1
                    logger.exception(
                        "refresh_metadata_series_failed",
                        series_id=series_id,
                        title=series_title,
                    )

            logger.info(
                "refresh_metadata_complete",
                refreshed=refreshed,
                failed=failed,
                total=len(stale_ids),
            )
        except Exception:
            await session.rollback()
            raise
