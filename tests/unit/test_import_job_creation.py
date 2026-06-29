"""Tests for import job creation helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from pullbox.core.exceptions import ValidationError
from pullbox.models.config import SystemConfig
from pullbox.models.import_job import ImportJob, ImportJobStatus, ImportSourceType
from pullbox.schemas.import_job import ImportJobCreate
from pullbox.services.import_job_creation import create_job

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def _log_event(
    _session: AsyncSession,
    _job_id: int,
    _level: str,
    _event: str,
    message: str | None = None,
    **kwargs: Any,
) -> None:
    _ = message, kwargs


async def test_create_job_uses_global_search_on_add_and_logs_event(
    db_session: AsyncSession,
    tmp_path: object,
) -> None:
    db_session.add(SystemConfig(key="search_on_add_default", value="true", value_type="bool"))
    await db_session.flush()
    events: list[tuple[str, dict[str, Any]]] = []

    async def log_event(
        _session: AsyncSession,
        _job_id: int,
        _level: str,
        event: str,
        message: str | None = None,
        **kwargs: Any,
    ) -> None:
        events.append((event, {"message": message, **kwargs}))

    request = ImportJobCreate(
        source_path=str(tmp_path),
        source_type=ImportSourceType.FILESYSTEM,
        monitored=False,
    )

    job = await create_job(db_session, request, log_event=log_event)

    assert job.status == ImportJobStatus.PENDING
    assert job.monitored is True
    assert job.search_on_add is True
    assert job.source_path == str(tmp_path)
    assert job.progress_snapshot["phase"] == "inventory"
    assert job.ingest_policy_snapshot["post_processing_method"] == "move"
    assert "comic_file_template" in job.ingest_policy_snapshot
    assert job.transfer_method == "move"
    assert job.effective_transfer_method == "copy"
    assert job.source_preserved is True
    assert events == [
        (
            "import_job_created",
            {
                "message": "Import job created for filesystem source",
                "source_path": str(tmp_path),
                "selected_file_count": 0,
            },
        )
    ]


async def test_create_job_rejects_conflicting_compat_search_on_add(
    db_session: AsyncSession,
    tmp_path: object,
) -> None:
    db_session.add(SystemConfig(key="search_on_add_default", value="true", value_type="bool"))
    await db_session.flush()
    request = ImportJobCreate(
        source_path=str(tmp_path),
        source_type=ImportSourceType.FILESYSTEM,
        search_on_add=False,
    )

    with pytest.raises(ValidationError, match="global import policy"):
        await create_job(db_session, request, log_event=_log_event)


async def test_create_job_rejects_existing_active_import(
    db_session: AsyncSession,
    tmp_path: object,
) -> None:
    db_session.add(
        ImportJob(
            source_path=str(tmp_path),
            source_type=ImportSourceType.FILESYSTEM,
            status=ImportJobStatus.REVIEW,
        )
    )
    await db_session.flush()
    request = ImportJobCreate(
        source_path=str(tmp_path),
        source_type=ImportSourceType.FILESYSTEM,
    )

    with pytest.raises(ValidationError, match="Only one import can be active"):
        await create_job(db_session, request, log_event=_log_event)
