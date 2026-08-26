"""Expose direct acquisitions through the established download-history contract."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import or_, select, update

from pullbox.core.acquisition import AcquisitionProtocol
from pullbox.models.blocklist import BlocklistEntry
from pullbox.models.direct_acquisition import (
    DirectAcquisitionAttempt,
    DirectAcquisitionState,
    DirectArtifactAttempt,
)
from pullbox.models.download import DownloadClientType, DownloadHistory, DownloadState
from pullbox.models.issue import Issue, IssueStatus

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession


_ACTIVE_ISSUE_STATES = frozenset(
    {
        DirectAcquisitionState.RESOLVING,
        DirectAcquisitionState.PLANNED,
        DirectAcquisitionState.QUEUED,
        DirectAcquisitionState.DOWNLOADING,
        DirectAcquisitionState.VALIDATING,
        DirectAcquisitionState.POST_PROCESSING,
        DirectAcquisitionState.RETRY_PENDING,
        DirectAcquisitionState.PAUSED,
    }
)
_FAILED_ISSUE_STATES = frozenset(
    {
        DirectAcquisitionState.CANCELLED,
        DirectAcquisitionState.FAILED,
    }
)


async def ensure_direct_download_history(
    session: AsyncSession,
    attempt: DirectAcquisitionAttempt,
    artifact: DirectArtifactAttempt,
    *,
    at: datetime,
) -> DownloadHistory:
    """Create or return the URL-safe download row for a direct attempt."""
    external_id = f"direct:{attempt.id}"
    download_url = f"pullbox-direct://attempt/{attempt.id}"
    result = await session.execute(
        select(DownloadHistory)
        .where(
            DownloadHistory.download_client == DownloadClientType.DIRECT,
            or_(
                DownloadHistory.external_id == external_id,
                DownloadHistory.download_url == download_url,
            ),
        )
        .order_by(
            (DownloadHistory.external_id == external_id).desc(),
            DownloadHistory.id.desc(),
        )
    )
    histories = list(result.scalars())
    if histories:
        history = histories[0]
        history.external_id = external_id
        history.download_url = download_url
        duplicate_ids = [duplicate.id for duplicate in histories[1:]]
        if duplicate_ids:
            await session.execute(
                update(BlocklistEntry)
                .where(BlocklistEntry.download_history_id.in_(duplicate_ids))
                .values(download_history_id=history.id)
            )
            for duplicate in histories[1:]:
                await session.delete(duplicate)
            await session.flush()
        return history

    display_title = str(
        attempt.candidate_snapshot.get("display_title") or attempt.provider_candidate_id
    )
    history = DownloadHistory(
        issue_id=attempt.issue_id,
        title=display_title,
        download_url=download_url,
        download_client=DownloadClientType.DIRECT,
        protocol=AcquisitionProtocol.DIRECT,
        external_id=external_id,
        state=DownloadState.QUEUED,
        file_size=artifact.expected_size,
        sent_at=at,
        replace_existing_file=attempt.replace_existing_file,
    )
    session.add(history)
    await session.flush()
    return history


async def sync_direct_download_history(
    session: AsyncSession,
    attempt: DirectAcquisitionAttempt,
    artifact: DirectArtifactAttempt,
    *,
    at: datetime,
    final_path: str | None = None,
) -> DownloadHistory:
    """Project durable direct state onto the existing download UI record."""
    history = await ensure_direct_download_history(session, attempt, artifact, at=at)
    history.state = _download_state(DirectAcquisitionState(attempt.state))
    history.file_size = artifact.expected_size
    history.retry_count = attempt.retry_count
    history.max_retries = attempt.max_retries
    history.next_retry_at = attempt.next_retry_at
    history.error_message = attempt.error_message

    if attempt.state is DirectAcquisitionState.COMPLETED:
        history.completed_at = at
        history.imported_at = at
        history.final_path = final_path
    elif attempt.state is DirectAcquisitionState.CANCELLED:
        history.completed_at = at
        history.error_message = "Cancelled by user"
    elif attempt.state is DirectAcquisitionState.FAILED:
        history.completed_at = at
    await _sync_issue_status(session, attempt)
    return history


async def _sync_issue_status(
    session: AsyncSession,
    attempt: DirectAcquisitionAttempt,
) -> None:
    """Keep direct acquisitions aligned with the shared issue-status contract."""
    issue = await session.get(Issue, attempt.issue_id)
    if issue is None:
        return

    state = DirectAcquisitionState(attempt.state)
    if state in _ACTIVE_ISSUE_STATES:
        issue.status = IssueStatus.DOWNLOADING
    elif state in _FAILED_ISSUE_STATES and issue.status is IssueStatus.DOWNLOADING:
        issue.status = IssueStatus.WANTED


def _download_state(state: DirectAcquisitionState) -> DownloadState:
    if state in {DirectAcquisitionState.PLANNED, DirectAcquisitionState.QUEUED}:
        return DownloadState.QUEUED
    if state is DirectAcquisitionState.RESOLVING:
        return DownloadState.SENT
    if state is DirectAcquisitionState.DOWNLOADING:
        return DownloadState.DOWNLOADING
    if state in {
        DirectAcquisitionState.VALIDATING,
        DirectAcquisitionState.POST_PROCESSING,
    }:
        return DownloadState.POST_PROCESSING
    if state is DirectAcquisitionState.COMPLETED:
        return DownloadState.IMPORTED
    if state is DirectAcquisitionState.RETRY_PENDING:
        return DownloadState.RETRY_PENDING
    if state is DirectAcquisitionState.PAUSED:
        return DownloadState.PAUSED
    return DownloadState.FAILED
