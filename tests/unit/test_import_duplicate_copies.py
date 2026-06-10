"""Tests for import duplicate-copy detection helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

from sqlalchemy import select

from pullbox.models.import_job import (
    ImportedFile,
    ImportedFileStatus,
    ImportedSeries,
    ImportJob,
    ImportJobLog,
    ImportJobStatus,
    ImportSeriesStatus,
    ImportSourceType,
)
from pullbox.services.import_service import ImportService

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession


def _make_service() -> ImportService:
    return ImportService(
        series_service=AsyncMock(),
        metadata_service=AsyncMock(),
        event_bus=AsyncMock(),
    )


async def _create_job_row(session: AsyncSession) -> ImportJob:
    job = ImportJob(
        source_path="/tmp/comics",
        source_type=ImportSourceType.FILESYSTEM,
        status=ImportJobStatus.FILE_MATCHING,
    )
    session.add(job)
    await session.flush()
    return job


async def _create_imported_series(
    session: AsyncSession,
    job: ImportJob,
    *,
    status: ImportSeriesStatus = ImportSeriesStatus.MATCHED,
) -> ImportedSeries:
    series = ImportedSeries(
        import_job_id=job.id,
        raw_series_name="Absolute Wonder Woman",
        status=status,
    )
    session.add(series)
    await session.flush()
    return series


def _make_imported_file(
    job: ImportJob,
    series: ImportedSeries,
    *,
    name: str,
    path: str | None = None,
    file_size: int = 1024,
    status: ImportedFileStatus = ImportedFileStatus.MATCHED,
    matched_issue_id: int | None = None,
    parsed_issue_number: float | None = 19.0,
) -> ImportedFile:
    return ImportedFile(
        import_job_id=job.id,
        import_series_id=series.id,
        file_path=path or f"/tmp/comics/{name}",
        file_name=name,
        file_size=file_size,
        file_format="cbz",
        status=status,
        matched_issue_id=matched_issue_id,
        parsed_issue_number=parsed_issue_number,
        include_in_import=True,
        is_preferred=True,
    )


async def test_detect_duplicate_copies_collapses_exact_same_target_files(
    db_session: AsyncSession,
) -> None:
    service = _make_service()
    job = await _create_job_row(db_session)
    series = await _create_imported_series(db_session, job)
    representative = _make_imported_file(
        job,
        series,
        name="Absolute Wonder Woman 019.cbz",
    )
    duplicate = _make_imported_file(
        job,
        series,
        name="Absolute Wonder Woman 019.cbz",
    )
    db_session.add_all([representative, duplicate])
    await db_session.flush()

    duplicate_count, group_counter, details = await service._detect_duplicate_copies(
        db_session,
        job,
        series,
        [representative, duplicate],
        0,
    )

    assert duplicate_count == 1
    assert group_counter == 1
    assert details[0]["duplicate_reason"] == "exact_duplicate"
    assert representative.status == ImportedFileStatus.MATCHED
    assert duplicate.status == ImportedFileStatus.DUPLICATE_FILE
    assert duplicate.include_in_import is False
    assert duplicate.is_preferred is False
    assert duplicate.duplicate_group_id == 1
    assert duplicate.duplicate_of_file_id == representative.id
    assert duplicate.diagnostics["kind"] == "duplicate_copy"
    assert duplicate.diagnostics["representative_file_name"] == representative.file_name

    log = (
        await db_session.execute(
            select(ImportJobLog).where(
                ImportJobLog.import_job_id == job.id,
                ImportJobLog.event == "import_duplicate_copy_exact_cluster",
            )
        )
    ).scalar_one()
    assert log.data["diagnostics"]["duplicate_group_id"] == 1
    assert log.data["diagnostics"]["files"][0]["is_representative"] is True


async def test_detect_duplicate_copies_hash_confirms_same_size_variants(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    service = _make_service()
    job = await _create_job_row(db_session)
    series = await _create_imported_series(db_session, job)
    first_path = tmp_path / "variant-a.cbz"
    second_path = tmp_path / "variant-b.cbz"
    first_path.write_bytes(b"same archive bytes")
    second_path.write_bytes(b"same archive bytes")
    representative = _make_imported_file(
        job,
        series,
        name="Absolute Wonder Woman 019 (Digital).cbz",
        path=str(first_path),
        file_size=first_path.stat().st_size,
    )
    duplicate = _make_imported_file(
        job,
        series,
        name="Absolute Wonder Woman 019 (2025).cbz",
        path=str(second_path),
        file_size=second_path.stat().st_size,
    )
    db_session.add_all([representative, duplicate])
    await db_session.flush()

    duplicate_count, group_counter, details = await service._detect_duplicate_copies(
        db_session,
        job,
        series,
        [representative, duplicate],
        41,
    )

    assert duplicate_count == 1
    assert group_counter == 42
    assert details[0]["duplicate_reason"] == "hash_confirmed_duplicate"
    assert representative.content_hash is not None
    assert duplicate.content_hash == representative.content_hash
    assert duplicate.status == ImportedFileStatus.DUPLICATE_FILE
    assert duplicate.duplicate_group_id == 42
    assert duplicate.diagnostics["duplicate_reason"] == "hash_confirmed_duplicate"

    log = (
        await db_session.execute(
            select(ImportJobLog).where(
                ImportJobLog.import_job_id == job.id,
                ImportJobLog.event == "import_duplicate_copy_hash_confirmed",
            )
        )
    ).scalar_one()
    assert log.data["diagnostics"]["duplicate_reason"] == "hash_confirmed_duplicate"
