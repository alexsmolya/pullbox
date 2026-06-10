"""Completed-download post-processing queue drain."""

from __future__ import annotations

import asyncio
import time as _time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pullbox.database import get_session_factory
from pullbox.models.download import DownloadHistory, DownloadState
from pullbox.models.issue import Issue, IssueStatus
from pullbox.tasks.post_processing_progress import (
    PostProcessingPhase,
    _clear_post_processing,
    _mark_post_processing_complete,
    _set_post_processing_phase,
)

logger = structlog.get_logger(__name__)

RunPostProcessing = Callable[[AsyncSession, DownloadHistory], Awaitable[None]]
_process_completed_lock = asyncio.Lock()


async def process_completed(
    run_post_processing: RunPostProcessing,
    *,
    session_factory: Any | None = None,
    event_logger: Any | None = None,
) -> None:
    """Post-process downloads that completed but have not yet been imported."""
    log = event_logger or logger
    if _process_completed_lock.locked():
        log.debug("process_completed_skipped_locked")
        return

    await _process_completed_lock.acquire()
    try:
        factory = session_factory or get_session_factory()

        start: float | None = None
        queued_total = 0
        processed = 0
        failed = 0

        while True:
            # Drain the queue until no completed, unimported items remain.
            download_ids: list[int] = []
            async with factory() as session:
                try:
                    result = await session.execute(
                        select(DownloadHistory.id).where(
                            DownloadHistory.state == DownloadState.COMPLETED,
                            DownloadHistory.imported_at.is_(None),
                        )
                    )
                    download_ids = [row[0] for row in result.all()]
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise

            if not download_ids:
                if start is None:
                    return
                break

            if start is None:
                start = _time.monotonic()
                log.info("process_completed_start", count=len(download_ids))
            else:
                log.debug("process_completed_drain_batch", count=len(download_ids))

            queued_total += len(download_ids)

            # Process each download in its own session so file I/O does not
            # hold long SQLite write locks.
            for dl_id in download_ids:
                completed_age_ms: float | None = None
                handoff_start: float | None = None
                async with factory(autoflush=False) as session:
                    try:
                        download = await session.get(DownloadHistory, dl_id)
                        if (
                            not download
                            or download.state != DownloadState.COMPLETED
                            or download.imported_at is not None
                        ):
                            continue

                        completed_age_ms = (
                            max(
                                0.0,
                                (datetime.now(UTC) - download.completed_at).total_seconds() * 1000,
                            )
                            if download.completed_at is not None
                            else None
                        )
                        handoff_start = _time.monotonic()
                        log.info(
                            "post_processing_handoff_started",
                            download_id=dl_id,
                            completed_age_ms=round(completed_age_ms, 1)
                            if completed_age_ms is not None
                            else None,
                        )
                        _set_post_processing_phase(dl_id, PostProcessingPhase.RESOLVING_SOURCE)
                        await run_post_processing(session, download)

                        # State stays at COMPLETED; imported_at marks success.
                        download.imported_at = datetime.now(UTC)
                        download.error_message = None
                        _mark_post_processing_complete(dl_id)
                        processed += 1
                        log.info(
                            "post_processing_handoff_complete",
                            download_id=dl_id,
                            completed_age_ms=round(completed_age_ms, 1)
                            if completed_age_ms is not None
                            else None,
                            post_processing_duration_ms=round(
                                (_time.monotonic() - handoff_start) * 1000,
                                1,
                            ),
                        )

                        await session.commit()
                    except Exception as exc:
                        failed_duration_ms = (
                            round((_time.monotonic() - handoff_start) * 1000, 1)
                            if handoff_start is not None
                            else None
                        )
                        _clear_post_processing(dl_id)
                        await session.rollback()
                        failed += 1
                        # Mark failed in a fresh mini-session so the error is persisted.
                        async with factory() as err_session:
                            try:
                                dl = await err_session.get(DownloadHistory, dl_id)
                                if dl:
                                    dl.state = DownloadState.FAILED
                                    dl.error_message = str(exc) or "Post-processing failed"

                                    issue = await err_session.get(Issue, dl.issue_id)
                                    if issue and issue.status == IssueStatus.DOWNLOADING:
                                        issue.status = IssueStatus.WANTED

                                await err_session.commit()
                            except Exception:
                                await err_session.rollback()

                        log.info(
                            "post_processing_handoff_failed",
                            download_id=dl_id,
                            completed_age_ms=round(completed_age_ms, 1)
                            if completed_age_ms is not None
                            else None,
                            post_processing_duration_ms=failed_duration_ms,
                        )
                        log.exception(
                            "process_completed_failed",
                            download_id=dl_id,
                        )

        duration_ms = (_time.monotonic() - start) * 1000
        log.info(
            "process_completed_done",
            processed=processed,
            failed=failed,
            total=queued_total,
            duration_ms=round(duration_ms, 1),
        )
    finally:
        _process_completed_lock.release()
