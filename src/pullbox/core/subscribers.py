"""Event subscribers — handlers wired to the application event bus.

Each handler receives an event dataclass and performs side effects such as
updating database records or logging summaries.  Handlers obtain their own
database sessions since they run outside of request scope.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

from pullbox.database import get_session_factory
from pullbox.models.download import DownloadHistory
from pullbox.models.issue import Issue, IssueStatus
from pullbox.models.library import LibraryFile, MatchConfidence

if TYPE_CHECKING:
    from pullbox.core.events import (
        DownloadCompleted,
        DownloadFailed,
        FileMatched,
        SeriesAdded,
    )

logger = structlog.get_logger(__name__)

# Strong references to background tasks to prevent garbage collection
_background_tasks: set[asyncio.Task[None]] = set()


async def on_download_completed(event: DownloadCompleted) -> None:
    """Record the downloaded path when a download completes.

    Note: issue status is NOT set to OWNED here. That only happens
    in register_library_file() after post-processing successfully
    transfers and registers the file. This prevents orphaned "owned"
    issues with no library file.
    """
    log = logger.bind(
        download_id=event.download_id,
        issue_id=event.issue_id,
        file_path=event.file_path,
    )
    log.info("subscriber_download_completed")

    factory = get_session_factory()
    async with factory() as session:
        try:
            download = await session.get(DownloadHistory, event.download_id)
            if download:
                download.downloaded_path = event.file_path or download.downloaded_path

            await session.commit()
        except Exception:
            await session.rollback()
            log.exception("subscriber_download_completed_failed")


async def on_download_failed(event: DownloadFailed) -> None:
    """Revert the issue status to wanted when a download fails."""
    log = logger.bind(
        download_id=event.download_id,
        issue_id=event.issue_id,
        error=event.error,
    )
    log.warning("subscriber_download_failed")

    factory = get_session_factory()
    async with factory() as session:
        try:
            issue = await session.get(Issue, event.issue_id)
            if issue and issue.status == IssueStatus.DOWNLOADING:
                issue.status = IssueStatus.WANTED

            await session.commit()
        except Exception:
            await session.rollback()
            log.exception("subscriber_download_failed_error")


async def on_file_matched(event: FileMatched) -> None:
    """Update issue status and link library file on a high-confidence match."""
    log = logger.bind(
        library_file_id=event.library_file_id,
        issue_id=event.issue_id,
        confidence=event.confidence,
    )
    log.info("subscriber_file_matched")

    factory = get_session_factory()
    async with factory() as session:
        try:
            library_file = await session.get(LibraryFile, event.library_file_id)
            if library_file:
                library_file.issue_id = event.issue_id

            if event.confidence in (MatchConfidence.HIGH, MatchConfidence.MANUAL):
                issue = await session.get(Issue, event.issue_id)
                if issue:
                    issue.status = IssueStatus.OWNED

            await session.commit()
        except Exception:
            await session.rollback()
            log.exception("subscriber_file_matched_failed")


async def on_series_added(event: SeriesAdded) -> None:
    """Schedule background tasks for a newly added series.

    Launches cover downloads and indexer searches as background tasks so
    the calling request can commit and respond immediately.
    """
    cover_task = asyncio.create_task(_download_covers_for_series(event))
    _background_tasks.add(cover_task)
    cover_task.add_done_callback(_background_tasks.discard)

    search_task = asyncio.create_task(_search_new_series(event))
    _background_tasks.add(search_task)
    search_task.add_done_callback(_background_tasks.discard)


async def _download_covers_for_series(event: SeriesAdded) -> None:
    """Download cover images for a series and its issues in the background.

    Uses the CDN URLs persisted on each record to download local copies.
    Each download uses its own session to avoid expiry issues after commit.
    """
    from sqlalchemy import select

    from pullbox.core.comicvine_key import get_comicvine_api_key
    from pullbox.models.series import Series
    from pullbox.providers.metadata.comicvine import ComicVineProvider
    from pullbox.services.metadata_service import MetadataService

    log = logger.bind(series_id=event.series_id)
    log.info("subscriber_cover_download_start")

    # Small delay to let the triggering request commit first
    await asyncio.sleep(1.0)

    factory = get_session_factory()

    # Load series info and build a work list in one session, then close it
    try:
        async with factory() as session:
            series = await session.get(Series, event.series_id)
            if not series:
                log.warning("subscriber_cover_download_series_not_found")
                return

            api_key = await get_comicvine_api_key(session)
            series_id = series.id
            series_cover_url = series.cover_url
            series_has_cover = bool(series.cover_path)

            # Collect issue cover work list: (issue_id, cover_url, issue_number)
            result = await session.execute(
                select(Issue.id, Issue.cover_url, Issue.issue_number).where(
                    Issue.series_id == event.series_id,
                    Issue.cover_url.isnot(None),
                    Issue.cover_path.is_(None),
                )
            )
            issue_work: list[tuple[int, str, float]] = [
                (row.id, row.cover_url, row.issue_number) for row in result.all()
            ]
    except Exception:
        log.exception("subscriber_cover_download_load_failed")
        return

    # Resolve the .covers/ directory (under comics_directory or legacy fallback)
    from pullbox.services.cover_resolver import resolve_covers_dir

    try:
        async with factory() as session:
            covers_base = await resolve_covers_dir(session)
    except Exception:
        log.exception("subscriber_cover_resolve_dir_failed")
        return

    covers_dir = covers_base / str(series_id)

    provider = ComicVineProvider(api_key=api_key)
    svc = MetadataService(provider=provider, covers_dir=covers_base)

    # Download series cover
    if series_cover_url and not series_has_cover:
        try:
            series_cover_dest = covers_dir / "series.jpg"
            await svc.download_cover(series_cover_url, series_cover_dest)
            if series_cover_dest.exists():
                async with factory() as session:
                    series_obj = await session.get(Series, series_id)
                    if series_obj and not series_obj.cover_path:
                        series_obj.cover_path = f"/api/v1/series/{series_id}/cover"
                        await session.commit()
                        log.info("subscriber_series_cover_downloaded")
        except Exception:
            log.exception("subscriber_series_cover_failed")

    # Download issue covers
    downloaded = 0
    for issue_id, cover_url, issue_number in issue_work:
        try:
            num_str = (
                f"{int(issue_number):03d}"
                if issue_number == int(issue_number)
                else f"{issue_number:06.1f}"
            )
            cover_dest = covers_dir / f"issue_{num_str}.jpg"
            await svc.download_cover(cover_url, cover_dest)
            if cover_dest.exists():
                async with factory() as session:
                    issue_obj = await session.get(Issue, issue_id)
                    if issue_obj and not issue_obj.cover_path:
                        issue_obj.cover_path = f"/api/v1/issues/{issue_id}/cover"
                        await session.commit()
                        downloaded += 1
        except Exception:
            log.exception("subscriber_issue_cover_failed", issue_id=issue_id)

        # Small delay to respect CDN rate limits
        await asyncio.sleep(0.2)

    log.info(
        "subscriber_cover_download_complete",
        total_issues=len(issue_work),
        downloaded=downloaded,
    )


async def _search_new_series(event: SeriesAdded) -> None:
    """Search indexers for wanted issues if the series is monitored.

    Checks the series' ``monitored`` flag before triggering a search.
    Delegates the actual search to ``search_series_issues()`` in the
    search task module.
    """
    from pullbox.models.series import IssueCatalogState, Series

    log = logger.bind(series_id=event.series_id)
    log.info("subscriber_series_added_search_start")

    # Small delay to let the triggering request commit first
    await asyncio.sleep(0.5)

    factory = get_session_factory()
    async with factory() as session:
        series = await session.get(Series, event.series_id)
        if not series:
            log.warning("subscriber_series_added_not_found")
            return

        if not series.monitored:
            log.info(
                "subscriber_series_added_search_skipped",
                reason="series is not monitored",
            )
            return
        if series.issue_catalog_state != IssueCatalogState.COMPLETE:
            log.info(
                "subscriber_series_added_search_skipped",
                reason="issue catalog is not complete",
                issue_catalog_state=series.issue_catalog_state.value,
            )
            return

    # Series is monitored — delegate to reusable helper
    from pullbox.tasks.search_task import search_series_issues

    await search_series_issues(event.series_id)
