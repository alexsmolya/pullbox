"""Download retry and orphan recovery helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import selectinload

from pullbox.models.download import DownloadHistory, DownloadState
from pullbox.models.issue import Issue, IssueStatus
from pullbox.tasks.download_stall_recovery import _recover_stalled_downloads

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from pullbox.services.download_service import DownloadService

logger = structlog.get_logger(__name__)

_STALE_DOWNLOAD_TIMEOUT = timedelta(minutes=10)


async def _recover_orphaned_downloads(
    session: AsyncSession,
) -> int:
    """Recover downloads and issues stuck in transient states."""
    now = datetime.now(UTC)
    recovered = 0

    recovered += await _recover_stalled_downloads(session)

    stale_cutoff = now - _STALE_DOWNLOAD_TIMEOUT
    result = await session.execute(
        select(DownloadHistory).where(
            DownloadHistory.state.in_([DownloadState.SENT, DownloadState.DOWNLOADING]),
            DownloadHistory.external_id.is_(None),
            DownloadHistory.updated_at < stale_cutoff,
        )
    )
    stale = list(result.scalars().all())
    for download in stale:
        logger.warning(
            "recover_stale_download",
            download_id=download.id,
            issue_id=download.issue_id,
            state=download.state,
            hint="Download has no external_id — client never accepted it.",
        )
        download.state = DownloadState.FAILED
        download.error_message = "Download client never acknowledged this download"

        issue = await session.get(Issue, download.issue_id)
        if issue and issue.status == IssueStatus.DOWNLOADING:
            issue.status = IssueStatus.WANTED
        recovered += 1

    result = await session.execute(
        select(DownloadHistory).where(
            DownloadHistory.state == DownloadState.FAILED,
            or_(
                DownloadHistory.error_message.contains("Operation not permitted"),
                DownloadHistory.error_message.contains("Input/output error"),
                DownloadHistory.error_message.contains("Not a directory"),
            ),
        )
    )
    perm_failed = list(result.scalars().all())
    for download in perm_failed:
        logger.info(
            "recover_xattr_failed_download",
            download_id=download.id,
            issue_id=download.issue_id,
            hint="Resetting xattr-failed download to COMPLETED for re-processing.",
        )
        download.state = DownloadState.COMPLETED
        download.error_message = None

        issue = await session.get(Issue, download.issue_id)
        if issue and issue.status == IssueStatus.WANTED:
            issue.status = IssueStatus.DOWNLOADING

        recovered += 1

    issue_result = await session.execute(
        select(Issue)
        .options(selectinload(Issue.library_file))
        .where(Issue.status == IssueStatus.DOWNLOADING)
    )
    downloading_issues: list[Issue] = list(issue_result.scalars().all())

    for orphan_issue in downloading_issues:
        active_result = await session.execute(
            select(DownloadHistory.id)
            .where(
                DownloadHistory.issue_id == orphan_issue.id,
                or_(
                    DownloadHistory.state.in_(
                        [
                            DownloadState.QUEUED,
                            DownloadState.SENT,
                            DownloadState.DOWNLOADING,
                            DownloadState.PAUSED,
                            DownloadState.RETRY_PENDING,
                        ]
                    ),
                    and_(
                        DownloadHistory.state == DownloadState.COMPLETED,
                        DownloadHistory.imported_at.is_(None),
                    ),
                ),
            )
            .limit(1)
        )
        has_active = active_result.scalar_one_or_none() is not None

        if not has_active:
            logger.warning(
                "recover_orphaned_issue",
                issue_id=orphan_issue.id,
                hint="Issue stuck in DOWNLOADING with no active download records.",
            )
            orphan_issue.status = (
                IssueStatus.OWNED if orphan_issue.library_file is not None else IssueStatus.WANTED
            )
            recovered += 1

    if recovered:
        logger.info("orphan_recovery_complete", recovered=recovered)

    return recovered


async def _process_retry_pending(
    factory: async_sessionmaker[AsyncSession],
    download_svc: DownloadService,
) -> int:
    """Re-trigger downloads whose retry time has elapsed."""
    now = datetime.now(UTC)
    async with factory() as session:
        result = await session.execute(
            select(DownloadHistory.id, DownloadHistory.retry_count).where(
                DownloadHistory.state == DownloadState.RETRY_PENDING,
                DownloadHistory.next_retry_at <= now,
            )
        )
        pending = [(row[0], row[1]) for row in result.all()]

    retried = 0
    for download_id, retry_count in pending:
        log = logger.bind(
            download_id=download_id,
            retry_count=retry_count,
        )
        try:
            async with factory() as session:
                await download_svc.retry_download(session, download_id)
                await session.commit()
            retried += 1
            log.info("download_retry_triggered")
        except Exception:
            log.exception("download_retry_trigger_failed")

    return retried
