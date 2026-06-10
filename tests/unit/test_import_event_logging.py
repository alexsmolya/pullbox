"""Tests for structured import event logging helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from sqlalchemy import select

from pullbox.models.import_job import ImportJob, ImportJobLog, ImportJobStatus, ImportSourceType
from pullbox.services.import_event_logging import log_import_event

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def _create_job_row(session: AsyncSession) -> ImportJob:
    job = ImportJob(
        source_path="/tmp/comics",
        source_type=ImportSourceType.FILESYSTEM,
        status=ImportJobStatus.PENDING,
    )
    session.add(job)
    await session.flush()
    return job


async def test_log_import_event_persists_sanitized_detail_only_event(
    db_session: AsyncSession,
) -> None:
    job = await _create_job_row(db_session)
    detail_bound = MagicMock()
    summary_bound = MagicMock()
    detail_logger = MagicMock()
    root_logger = MagicMock()
    detail_logger.bind.return_value = detail_bound
    root_logger.bind.return_value = summary_bound

    log_import_event(
        db_session,
        job.id,
        "INFO",
        "import_file_placed",
        message="Using postgres://pullbox:secretpass@db.internal/pullbox",
        detail_logger=detail_logger,
        root_logger=root_logger,
        data={"api_key": "abc123"},
    )
    await db_session.flush()

    result = await db_session.execute(
        select(ImportJobLog).where(ImportJobLog.import_job_id == job.id)
    )
    log = result.scalar_one()
    assert log.event == "import_file_placed"
    assert log.level == "INFO"
    assert "***REDACTED***" in (log.message or "")
    assert log.data["api_key"] == "***REDACTED***"
    detail_bound.info.assert_called_once()
    summary_bound.info.assert_not_called()


async def test_log_import_event_mirrors_lifecycle_summary_event(
    db_session: AsyncSession,
) -> None:
    job = await _create_job_row(db_session)
    detail_bound = MagicMock()
    summary_bound = MagicMock()
    detail_logger = MagicMock()
    root_logger = MagicMock()
    detail_logger.bind.return_value = detail_bound
    root_logger.bind.return_value = summary_bound

    log_import_event(
        db_session,
        job.id,
        "INFO",
        "import_scan_completed",
        message="Scan complete.",
        detail_logger=detail_logger,
        root_logger=root_logger,
        data={"series_found": 12},
    )

    detail_bound.info.assert_called_once()
    summary_bound.info.assert_called_once()
