"""Adapter from direct quarantine into Pullbox's existing ingest pipeline."""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

from sqlalchemy import select

from pullbox.models.download import DownloadState
from pullbox.models.library import LibraryFile
from pullbox.tasks.download_task import _run_post_processing

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from sqlalchemy.ext.asyncio import AsyncSession


class _PostProcessor(Protocol):
    def __call__(
        self,
        session: Any,
        download: Any,
        *,
        resolve_local_path: Any,
        cleanup_source: bool,
        allow_resource_safety_exception: bool,
    ) -> Awaitable[None]: ...


@dataclass(frozen=True, slots=True)
class _DirectClient:
    value: str = "direct"
    is_torrent: bool = False
    is_usenet: bool = False


@dataclass(slots=True)
class _DirectPostProcessingRecord:
    """Ephemeral download-shaped adapter; it is never added to the database."""

    id: int
    issue_id: int
    title: str
    downloaded_path: str
    replace_existing_file: bool
    download_client: _DirectClient
    download_url: str
    state: DownloadState
    final_path: str | None = None
    imported_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class DirectPostProcessingResult:
    """Library linkage returned by the unchanged post-processing pipeline."""

    library_file_id: int
    final_path: Path


async def run_direct_artifact_post_processing(
    session: AsyncSession,
    *,
    acquisition_id: int,
    issue_id: int,
    source_path: Path,
    replace_existing_file: bool,
    allow_resource_safety_exception: bool = False,
    post_processor: _PostProcessor | None = None,
) -> DirectPostProcessingResult:
    """Process one quarantined comic without client path mapping or cleanup."""
    if acquisition_id < 1 or issue_id < 1:
        raise ValueError("Direct acquisition and issue IDs must be positive.")
    record = _DirectPostProcessingRecord(
        id=-acquisition_id,
        issue_id=issue_id,
        title=source_path.name,
        downloaded_path=str(source_path),
        replace_existing_file=replace_existing_file,
        download_client=_DirectClient(),
        download_url=f"direct://attempt/{acquisition_id}",
        state=DownloadState.COMPLETED,
    )
    processor = post_processor or cast("_PostProcessor", _run_post_processing)
    await processor(
        session,
        record,
        resolve_local_path=_resolve_direct_source,
        cleanup_source=False,
        allow_resource_safety_exception=allow_resource_safety_exception,
    )
    await session.flush()
    result = await session.execute(select(LibraryFile).where(LibraryFile.issue_id == issue_id))
    library_file = result.scalar_one_or_none()
    if library_file is None:
        raise RuntimeError("Direct artifact post-processing did not register a library file.")
    final_path = Path(library_file.file_path)
    await asyncio.to_thread(
        _materialize_library_symlink,
        final_path,
        source_path,
    )
    record.imported_at = datetime.now(UTC)
    return DirectPostProcessingResult(
        library_file_id=library_file.id,
        final_path=final_path,
    )


async def _resolve_direct_source(
    _session: AsyncSession,
    download: _DirectPostProcessingRecord,
) -> str:
    return download.downloaded_path


def _materialize_library_symlink(final_path: Path, source_path: Path) -> None:
    """Replace a direct-import symlink before its quarantine target is removed."""
    if not final_path.is_symlink():
        return
    try:
        target = final_path.resolve(strict=True)
        source = source_path.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError("Direct artifact symlink target is unavailable.") from exc
    if target != source:
        return

    descriptor, temporary_name = tempfile.mkstemp(
        dir=final_path.parent,
        prefix=f".{final_path.name}.pullbox-direct-",
        suffix=".tmp",
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, final_path)
    finally:
        temporary.unlink(missing_ok=True)
