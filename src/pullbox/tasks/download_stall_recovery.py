"""Stalled download recovery helpers."""

from __future__ import annotations

import time as _time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select

from pullbox.core.config_resolver import get_int_setting, load_system_config_values
from pullbox.models.download import DownloadClientType, DownloadHistory, DownloadState
from pullbox.models.issue import Issue, IssueStatus
from pullbox.tasks.download_failure import (
    auto_blocklist_on_download_failure,
    handle_download_failure,
)
from pullbox.tasks.download_progress import (
    _clear_progress,
    _progress_cache,
    _stall_first_seen,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

_STALLED_DOWNLOAD_TIMEOUT = timedelta(hours=1)
_STALL_TIMEOUT_CONFIG_KEY = "stall_timeout_hours"


async def _get_stall_timeout(session: AsyncSession) -> timedelta:
    """Read the stall timeout from SystemConfig, falling back to the default."""
    default_hours = int(_STALLED_DOWNLOAD_TIMEOUT.total_seconds() // 3600)
    configs = await load_system_config_values(session, (_STALL_TIMEOUT_CONFIG_KEY,))
    hours = get_int_setting(configs, _STALL_TIMEOUT_CONFIG_KEY, default_hours)
    if hours > 0:
        return timedelta(hours=hours)

    logger.warning(
        "invalid_stall_timeout_config",
        value=configs.get(_STALL_TIMEOUT_CONFIG_KEY),
    )
    return _STALLED_DOWNLOAD_TIMEOUT


async def _handle_stalled_download_failure(
    session: AsyncSession,
    download: DownloadHistory,
    error_message: str,
) -> None:
    """Handle a stalled download using the normal retry/blocklist policy."""
    await handle_download_failure(
        session,
        download,
        error_message,
        auto_blocklist_on_failure=auto_blocklist_on_download_failure,
    )


async def _reset_issue_for_permanent_failure(
    session: AsyncSession,
    download: DownloadHistory,
) -> None:
    """Reset the related issue only when the download permanently failed."""
    if download.state != DownloadState.FAILED:
        return
    issue = await session.get(Issue, download.issue_id)
    if issue and issue.status == IssueStatus.DOWNLOADING:
        issue.status = IssueStatus.WANTED


async def _recover_stalled_downloads(
    session: AsyncSession,
) -> int:
    """Recover active download records that have stalled."""
    now = datetime.now(UTC)
    timeout = await _get_stall_timeout(session)
    stall_cutoff = now - timeout
    timeout_seconds = timeout.total_seconds()
    timeout_minutes = int(timeout_seconds // 60)
    recovered = 0

    result = await session.execute(
        select(DownloadHistory).where(
            DownloadHistory.state.in_([DownloadState.DOWNLOADING, DownloadState.FINALIZING]),
            DownloadHistory.download_client != DownloadClientType.DIRECT,
            DownloadHistory.external_id.isnot(None),
            DownloadHistory.updated_at < stall_cutoff,
        )
    )
    stalled_ids: set[int] = set()

    for download in result.scalars().all():
        stalled_ids.add(download.id)
        snapshot = _progress_cache.get(download.id)

        logger.warning(
            "recover_stalled_download",
            download_id=download.id,
            issue_id=download.issue_id,
            reason="no_heartbeat",
            minutes_stalled=round(
                (now - download.updated_at.replace(tzinfo=UTC)).total_seconds() / 60
            ),
            client_state=snapshot.client_state if snapshot else None,
        )

        error_msg = f"Download stalled — no progress for {timeout_minutes} minutes"
        await _handle_stalled_download_failure(session, download, error_msg)
        _clear_progress(download.id)
        await _reset_issue_for_permanent_failure(session, download)
        recovered += 1

    now_mono = _time.monotonic()
    for dl_id, first_seen in list(_stall_first_seen.items()):
        if dl_id in stalled_ids:
            continue
        elapsed = now_mono - first_seen
        if elapsed < timeout_seconds:
            continue

        dl_obj = await session.get(DownloadHistory, dl_id)
        if not dl_obj or dl_obj.state not in {DownloadState.DOWNLOADING, DownloadState.FINALIZING}:
            _stall_first_seen.pop(dl_id, None)
            continue

        snapshot = _progress_cache.get(dl_id)
        client_state = snapshot.client_state if snapshot else "unknown"

        logger.warning(
            "recover_stalled_download",
            download_id=dl_id,
            issue_id=dl_obj.issue_id,
            reason="client_state_stall",
            minutes_stalled=round(elapsed / 60),
            client_state=client_state,
        )

        error_msg = (
            f"Download stalled — client reported '{client_state}' for {timeout_minutes} minutes"
        )
        await _handle_stalled_download_failure(session, dl_obj, error_msg)
        _clear_progress(dl_id)
        await _reset_issue_for_permanent_failure(session, dl_obj)
        recovered += 1

    return recovered
