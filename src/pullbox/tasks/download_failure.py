"""Download failure retry and auto-blocklist helpers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import structlog

from pullbox.core.config_resolver import load_system_config_values, parse_bool
from pullbox.models.download import DownloadHistory, DownloadState

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


logger = structlog.get_logger(__name__)

# Backoff intervals for retries: 15 minutes, 1 hour, 6 hours
RETRY_BACKOFF_SECONDS = [900, 3600, 21600]
_AUTO_BLOCKLIST_CONFIG_KEY = "blocklist.auto_add_on_failure"

AutoBlocklistHandler = Callable[["AsyncSession", DownloadHistory, str | None], Awaitable[None]]


def get_backoff_delay(retry_count: int) -> timedelta:
    """Return the backoff delay for the given retry attempt (0-indexed)."""
    idx = min(retry_count, len(RETRY_BACKOFF_SECONDS) - 1)
    return timedelta(seconds=RETRY_BACKOFF_SECONDS[idx])


async def handle_download_failure(
    session: AsyncSession,
    download: DownloadHistory,
    error_message: str | None,
    *,
    auto_blocklist_on_failure: AutoBlocklistHandler | None = None,
) -> None:
    """Handle a failed download: schedule retry or mark permanently failed.

    When retries are exhausted and blocklist.auto_add_on_failure is enabled,
    the release is automatically added to the blocklist.
    """
    log = logger.bind(download_id=download.id, issue_id=download.issue_id)
    auto_blocklist = auto_blocklist_on_failure or auto_blocklist_on_download_failure

    download.retry_count += 1
    download.error_message = error_message

    if download.retry_count < download.max_retries:
        delay = get_backoff_delay(download.retry_count - 1)
        download.next_retry_at = datetime.now(UTC) + delay
        download.state = DownloadState.RETRY_PENDING
        log.info(
            "download_retry_scheduled",
            retry_count=download.retry_count,
            max_retries=download.max_retries,
            next_retry_at=str(download.next_retry_at),
        )
    else:
        download.state = DownloadState.FAILED
        download.next_retry_at = None
        log.warning(
            "download_permanently_failed",
            retry_count=download.retry_count,
            max_retries=download.max_retries,
        )

        # Blocklist errors must never prevent the download from failing cleanly.
        try:
            await auto_blocklist(session, download, error_message)
        except Exception:
            logger.debug(
                "blocklist_auto_add_skipped",
                download_id=download.id,
                reason="error_during_blocklist_add",
            )


async def auto_blocklist_on_download_failure(
    session: AsyncSession,
    download: DownloadHistory,
    error_message: str | None,
) -> None:
    """Add a permanently failed download to the blocklist if config allows."""
    from pullbox.core.release_parser import parse_release_title
    from pullbox.models.blocklist import BlocklistReason
    from pullbox.services.blocklist_service import BlocklistService

    configs = await load_system_config_values(session, (_AUTO_BLOCKLIST_CONFIG_KEY,))
    auto_add = parse_bool(configs.get(_AUTO_BLOCKLIST_CONFIG_KEY))

    if not auto_add:
        logger.debug("blocklist_auto_add_disabled", download_id=download.id)
        return

    parsed = parse_release_title(download.title)
    release_group = parsed.scan_group if parsed else None

    entry = await BlocklistService.add_entry(
        session,
        download.title,
        BlocklistReason.FAILED,
        download_url=download.download_url,
        issue_id=download.issue_id,
        indexer_id=download.indexer_id,
        error_message=error_message,
        release_group=release_group,
        download_history_id=download.id,
    )

    if entry:
        logger.info(
            "blocklist_auto_added_on_failure",
            entry_id=entry.id,
            download_id=download.id,
            title=download.title,
        )
