"""Download service — orchestrates sending releases to download clients."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select

from pullbox.core.events import DownloadFailed, DownloadStarted, EventBus
from pullbox.core.exceptions import NotFoundError, ProviderError
from pullbox.models.download import DownloadClientType, DownloadHistory, DownloadState
from pullbox.models.issue import Issue, IssueStatus
from pullbox.services.download_history_classification import download_history_clause

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncSession

    from pullbox.providers.base import DownloadClient, ProviderRegistry, ReleaseResult

logger = structlog.get_logger(__name__)


class DownloadService:
    """Manages sending releases to download clients and tracking progress.

    Args:
        registry: Provider registry for accessing download clients.
        event_bus: For emitting download lifecycle events.
    """

    def __init__(
        self,
        registry: ProviderRegistry,
        event_bus: EventBus,
    ) -> None:
        self._registry = registry
        self._event_bus = event_bus

    async def send_to_client(
        self,
        session: AsyncSession,
        release: ReleaseResult,
        issue_id: int,
        indexer_id: int | None = None,
    ) -> DownloadHistory:
        """Send a release to the appropriate download client.

        Routes NZB releases to the NZB client (SABnzbd) and torrent
        releases to the torrent client (qBittorrent).
        """
        log = logger.bind(issue_id=issue_id, title=release.title, is_torrent=release.is_torrent)
        log.info("download_send_start")

        # Select the appropriate client
        client = self._select_client(release.is_torrent)
        if not client:
            protocol = "torrent" if release.is_torrent else "NZB"
            raise ProviderError("download", f"No {protocol} download client configured")

        # Record which client will handle this download
        client_type = DownloadClientType(client.client_type)
        download = DownloadHistory(
            issue_id=issue_id,
            indexer_id=indexer_id,
            title=release.title,
            download_url=release.download_url,
            download_client=client_type,
            state=DownloadState.QUEUED,
            file_size=release.size_bytes,
        )
        session.add(download)
        await session.flush()

        # Send to client
        try:
            if release.is_torrent:
                external_id = await client.add_torrent(release.download_url, release.title)
            else:
                external_id = await client.add_nzb(release.download_url, release.title)

            download.external_id = external_id
            download.state = DownloadState.SENT
            download.sent_at = datetime.now(UTC)

            # Update issue status
            issue = await session.get(Issue, issue_id)
            if issue:
                issue.status = IssueStatus.DOWNLOADING

            await self._event_bus.emit(
                DownloadStarted(
                    download_id=download.id,
                    issue_id=issue_id,
                    client_type=client_type,
                )
            )

            log.info("download_sent", external_id=external_id, client=client.name)

        except Exception as exc:
            download.state = DownloadState.FAILED
            download.error_message = str(exc)

            await self._event_bus.emit(
                DownloadFailed(
                    download_id=download.id,
                    issue_id=issue_id,
                    error=str(exc),
                )
            )
            log.error("download_send_failed", error=str(exc))

        return download

    async def grab_release(
        self,
        session: AsyncSession,
        issue_id: int,
        download_url: str,
        title: str,
        indexer_name: str,
        is_torrent: bool,
        file_size: int | None = None,
    ) -> DownloadHistory:
        """Grab a specific release selected by the user.

        Constructs a ReleaseResult and delegates to send_to_client().
        """
        from pullbox.providers.base import ReleaseResult

        release = ReleaseResult(
            title=title,
            indexer_name=indexer_name,
            download_url=download_url,
            size_bytes=file_size,
            age_days=None,
            seeders=None,
            leechers=None,
            grabs=None,
            is_torrent=is_torrent,
            category=None,
            published_at=None,
        )
        return await self.send_to_client(session, release, issue_id)

    async def check_active_downloads(
        self,
        session: AsyncSession,
        on_failure: Callable[[DownloadHistory, str | None], Awaitable[None]] | None = None,
    ) -> dict[str, int]:
        """Poll download clients for status updates on active downloads.

        Args:
            session: Database session.
            on_failure: Optional async callback invoked when a download fails.
                Receives the DownloadHistory and error message.  When provided,
                the callback is responsible for setting the download state.
                When ``None``, failures are marked FAILED and a DownloadFailed
                event is emitted immediately.

        Returns a summary of state transitions.
        """
        result = await session.execute(
            select(DownloadHistory).where(
                DownloadHistory.state.in_(
                    [
                        DownloadState.SENT,
                        DownloadState.DOWNLOADING,
                        DownloadState.FINALIZING,
                    ]
                )
            )
        )
        active = list(result.scalars().all())

        if not active:
            return {"checked": 0, "completed": 0, "failed": 0}

        completed = 0
        failed = 0

        for download in active:
            client = self.get_client_for_download(download)
            if not client:
                continue

            # If we don't have an external_id yet (e.g. add_torrent couldn't
            # detect the hash immediately), try to match by title.
            if not download.external_id:
                if hasattr(client, "find_torrent_by_title") and download.title:
                    try:
                        found_hash = await client.find_torrent_by_title(str(download.title))
                        if found_hash:
                            download.external_id = found_hash
                            logger.debug(
                                "download_matched_by_title",
                                download_id=download.id,
                                title=download.title,
                                external_id=found_hash,
                            )
                        else:
                            continue  # still not found, try next poll
                    except Exception:
                        logger.debug(
                            "download_title_match_failed",
                            download_id=download.id,
                        )
                        continue
                else:
                    continue

            try:
                status = await client.get_download_status(download.external_id)
            # noinspection PyBroadException
            except Exception:
                logger.exception(
                    "download_status_check_failed",
                    download_id=download.id,
                    external_id=download.external_id,
                )
                continue

            # Update state based on client status
            if status.state == "completed":
                download.state = DownloadState.COMPLETED
                download.completed_at = datetime.now(UTC)
                if status.downloaded_path:
                    download.downloaded_path = status.downloaded_path
                completed += 1

            elif status.state == "failed":
                failed += 1
                if on_failure:
                    await on_failure(download, status.error_message)
                else:
                    download.state = DownloadState.FAILED
                    download.error_message = status.error_message

            elif status.state == "downloading":
                download.state = DownloadState.DOWNLOADING
                if status.downloaded_path and not download.downloaded_path:
                    download.downloaded_path = status.downloaded_path

            elif status.state == "finalizing":
                download.state = DownloadState.FINALIZING
                if status.downloaded_path and not download.downloaded_path:
                    download.downloaded_path = status.downloaded_path

            elif status.state == "paused":
                download.state = DownloadState.PAUSED

        summary = {
            "checked": len(active),
            "completed": completed,
            "failed": failed,
        }
        logger.info("download_status_check_complete", **summary)
        return summary

    @staticmethod
    async def get_queue(session: AsyncSession) -> list[DownloadHistory]:
        """Get all active downloads (queued, sent, downloading)."""
        result = await session.execute(
            select(DownloadHistory)
            .where(
                DownloadHistory.state.in_(
                    [
                        DownloadState.QUEUED,
                        DownloadState.SENT,
                        DownloadState.DOWNLOADING,
                        DownloadState.FINALIZING,
                        DownloadState.PAUSED,
                    ]
                )
            )
            .order_by(DownloadHistory.created_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_history(
        session: AsyncSession,
        limit: int = 50,
        offset: int = 0,
    ) -> list[DownloadHistory]:
        """Get download history rows that belong on the downloads page."""
        result = await session.execute(
            select(DownloadHistory)
            .where(download_history_clause())
            .order_by(DownloadHistory.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def retry_download(
        self,
        session: AsyncSession,
        download_id: int,
    ) -> DownloadHistory:
        """Re-send a download to the download client (automated retry).

        Used by the retry scheduler when next_retry_at has elapsed.
        Preserves retry_count so backoff state is maintained.
        """
        download = await session.get(DownloadHistory, download_id)
        if not download:
            raise NotFoundError("DownloadHistory", download_id)

        log = logger.bind(
            download_id=download_id,
            retry_count=download.retry_count,
        )

        download.state = DownloadState.QUEUED
        download.error_message = None
        download.external_id = None
        download.sent_at = None
        download.next_retry_at = None

        # noinspection PyTypeChecker
        return await self._send_download(download, log)

    async def manual_retry(
        self,
        session: AsyncSession,
        download_id: int,
    ) -> DownloadHistory:
        """User-triggered retry that resets retry_count to 0."""
        download = await session.get(DownloadHistory, download_id)
        if not download:
            raise NotFoundError("DownloadHistory", download_id)

        if download.state not in (DownloadState.FAILED, DownloadState.RETRY_PENDING):
            from pullbox.core.exceptions import ValidationError

            raise ValidationError(
                f"Cannot retry download in state '{download.state}'",
            )

        log = logger.bind(download_id=download_id)

        # Reset retry state completely
        download.retry_count = 0
        download.state = DownloadState.QUEUED
        download.error_message = None
        download.external_id = None
        download.sent_at = None
        download.next_retry_at = None

        # noinspection PyTypeChecker
        return await self._send_download(download, log)

    async def _send_download(
        self,
        download: DownloadHistory,
        log: structlog.stdlib.BoundLogger,
    ) -> DownloadHistory:
        """Send a download to the appropriate client."""
        is_torrent = DownloadClientType(str(download.download_client)).is_torrent
        client = self._select_client(is_torrent)
        if not client:
            download.state = DownloadState.FAILED
            download.error_message = "No download client available"
            # noinspection PyTypeChecker
            return download

        try:
            if is_torrent:
                external_id = await client.add_torrent(
                    str(download.download_url), str(download.title)
                )
            else:
                external_id = await client.add_nzb(str(download.download_url), str(download.title))

            download.external_id = external_id
            download.state = DownloadState.SENT
            download.sent_at = datetime.now(UTC)

            log.info("download_retry_sent", external_id=external_id)
        except Exception as exc:
            download.state = DownloadState.FAILED
            download.error_message = str(exc)
            log.error("download_retry_failed", error=str(exc))

        # noinspection PyTypeChecker
        return download

    def _select_client(self, is_torrent: bool) -> DownloadClient | None:
        """Select the appropriate download client based on release type."""
        if is_torrent:
            return self._registry.get_torrent_client()
        return self._registry.get_nzb_client()

    def get_client_for_download(self, download: DownloadHistory) -> DownloadClient | None:
        """Get the client that handles a specific download by its client type."""
        return self._registry.get_client_for_type(str(download.download_client))

    def get_client_for_type(self, client_type: object) -> DownloadClient | None:
        """Get the client for a given DownloadClientType value."""
        return self._registry.get_client_for_type(str(client_type))
