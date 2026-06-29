"""Tests for import activity guards shared by background workers."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from pullbox.models.import_job import ImportJob, ImportJobStatus, ImportSourceType
from pullbox.services.import_activity import has_active_import_scheduler_protection


async def _create_import(db_session, status: ImportJobStatus) -> None:
    db_session.add(
        ImportJob(
            source_path="/imports/test",
            source_type=ImportSourceType.FILESYSTEM,
            status=status,
        )
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_import_scheduler_protection_includes_stalled_jobs(async_engine, db_session) -> None:
    await _create_import(db_session, ImportJobStatus.STALLED)
    factory = async_sessionmaker(async_engine, expire_on_commit=False)

    assert await has_active_import_scheduler_protection(factory) is True


@pytest.mark.asyncio
async def test_import_scheduler_protection_excludes_idle_review_and_paused_jobs(
    async_engine,
    db_session,
) -> None:
    await _create_import(db_session, ImportJobStatus.REVIEW)
    await _create_import(db_session, ImportJobStatus.PAUSED)
    factory = async_sessionmaker(async_engine, expire_on_commit=False)

    assert await has_active_import_scheduler_protection(factory) is False
