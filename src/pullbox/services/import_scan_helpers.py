"""Import scan setup and preflight helpers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import delete as sa_delete

from pullbox.core.file_safety import (
    FileSafetyError,
    classify_resource_safety_exception,
    get_archive_size_limit_bytes,
    is_dangerous_file_blocking_enabled,
    run_safety_checks,
)
from pullbox.models.import_job import ImportedFile, ImportedSeries, ImportJob

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from pullbox.core.collection_scanner import DiscoveredFile, DiscoveredSeries


FileSafetyCheck = Callable[["AsyncSession", Path], Awaitable[None]]


async def reset_scan_artifacts(session: AsyncSession, job: ImportJob) -> None:
    """Clear scan-produced rows and counters before a fresh/recovered scan run."""
    await session.execute(sa_delete(ImportedFile).where(ImportedFile.import_job_id == job.id))
    await session.execute(sa_delete(ImportedSeries).where(ImportedSeries.import_job_id == job.id))

    job.error_message = None
    job.progress_snapshot = {}
    job.scan_total_files = 0
    job.scan_total_dirs = 0
    job.series_found = 0
    job.series_duplicate = 0
    job.series_matched = 0
    job.series_no_match = 0
    job.series_new = 0
    job.total_files_found = 0
    job.total_files_matched = 0
    job.total_files_duplicate = 0
    job.total_files_already_owned = 0
    job.total_files_conflict = 0
    job.total_files_no_match = 0
    job.scan_started_at = None
    job.scan_completed_at = None
    job.match_started_at = None
    job.match_completed_at = None
    await session.flush()


async def _build_default_file_safety_check(session: AsyncSession) -> FileSafetyCheck:
    """Build a per-batch file safety checker with immutable config values."""
    block_dangerous = await is_dangerous_file_blocking_enabled(session)
    max_archive_size = await get_archive_size_limit_bytes(session)

    async def _check_file_safety(_session: AsyncSession, path: Path) -> None:
        run_safety_checks(
            path,
            block_dangerous=block_dangerous,
            max_archive_size=max_archive_size,
        )

    return _check_file_safety


async def validate_discovered_files_safety(
    session: AsyncSession,
    discovered_list: list[DiscoveredSeries],
    *,
    check_file_safety: FileSafetyCheck | None = None,
) -> None:
    """Run safety checks once per unique discovered source file."""
    effective_check_file_safety = check_file_safety
    if effective_check_file_safety is None:
        effective_check_file_safety = await _build_default_file_safety_check(session)

    files_by_path: dict[str, list[DiscoveredFile]] = {}
    for discovered in discovered_list:
        for discovered_file in discovered.files:
            files_by_path.setdefault(discovered_file.file_path, []).append(discovered_file)

    for file_path, discovered_files in files_by_path.items():
        try:
            await effective_check_file_safety(session, Path(file_path))
        except FileSafetyError as exc:
            resource_block = classify_resource_safety_exception(exc)
            safety_block = (
                resource_block.to_diagnostics()
                if resource_block is not None
                else {
                    "kind": "file_safety_blocked",
                    "reason": exc.reason,
                    "details": list(exc.details),
                    "source": "file_safety",
                    "overrideable": False,
                }
            )
            for discovered_file in discovered_files:
                metadata_diagnostics = dict(discovered_file.metadata_diagnostics)
                metadata_diagnostics["file_safety"] = safety_block
                discovered_file.metadata_diagnostics = metadata_diagnostics
