"""Adopt source folders that already live inside the active library root."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from sqlalchemy import select as sa_select

from pullbox.core.library_naming import build_series_folder_name
from pullbox.core.library_root_resolution import (
    path_is_inside_root,
    resolve_library_root,
)
from pullbox.models.import_job import ImportedFile, ImportedSeries, ImportJob
from pullbox.models.series import Series

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from sqlalchemy.ext.asyncio import AsyncSession

    from pullbox.core.library_policy import LibraryIngestPolicy
    from pullbox.models.import_job import ImportJobAction
    from pullbox.models.library import LibraryRoot


class RecordActionFunc(Protocol):
    async def __call__(
        self,
        session: AsyncSession,
        job: ImportJob,
        *,
        phase: str,
        action_type: str,
        payload: dict[str, Any],
    ) -> ImportJobAction: ...


class LogEventFunc(Protocol):
    def __call__(self, *args: Any, **kwargs: Any) -> Awaitable[None]: ...


@dataclass(frozen=True, slots=True)
class ImportSeriesFolderAdoptionPlan:
    """A safe one-folder adoption operation for a review row."""

    source_folder: Path
    target_folder: Path
    root: LibraryRoot
    series_id: int
    old_series_path: str | None
    old_library_root_id: int | None


async def plan_import_series_folder_adoption(
    session: AsyncSession,
    job: ImportJob,
    item: ImportedSeries,
    importable_files: list[ImportedFile],
    *,
    resolved_series_id: int,
    ingest_policy: LibraryIngestPolicy,
) -> ImportSeriesFolderAdoptionPlan | None:
    """Return a folder-adoption plan when the source folder can be renamed safely."""
    if not _folder_adoption_enabled(job, ingest_policy):
        return None
    if not importable_files:
        return None

    source_folder = _source_folder_for_item(item, importable_files)
    if source_folder is None or not source_folder.exists() or not source_folder.is_dir():
        return None

    series = await session.get(Series, resolved_series_id)
    if series is None:
        return None

    root = await resolve_library_root(
        session,
        source_folder,
        job.target_library_root_id,
        series=series,
    )
    root_path = _resolved_path(Path(root.path))
    resolved_source_folder = _resolved_path(source_folder)
    if resolved_source_folder == root_path or not path_is_inside_root(source_folder, root):
        return None

    target_folder = _target_folder_for_series(series, root, ingest_policy)
    resolved_target_folder = _resolved_path(target_folder)
    if resolved_target_folder == resolved_source_folder:
        return None
    if not resolved_target_folder.is_relative_to(root_path):
        return None
    if _target_folder_has_blocking_content(target_folder):
        return None

    if not _all_importable_files_are_inside_source(source_folder, importable_files):
        return None
    if await _source_folder_is_shared_by_other_review_rows(session, job, item, source_folder):
        return None
    if await _source_folder_has_imported_files_for_other_rows(session, job, item, source_folder):
        return None

    return ImportSeriesFolderAdoptionPlan(
        source_folder=source_folder,
        target_folder=target_folder,
        root=root,
        series_id=series.id,
        old_series_path=series.path,
        old_library_root_id=series.library_root_id,
    )


async def apply_import_series_folder_adoption(
    session: AsyncSession,
    job: ImportJob,
    item: ImportedSeries,
    importable_files: list[ImportedFile],
    *,
    resolved_series_id: int,
    ingest_policy: LibraryIngestPolicy,
    record_action: RecordActionFunc,
    log_event: LogEventFunc,
) -> bool:
    """Rename an adoptable source folder and update import review paths."""
    plan = await plan_import_series_folder_adoption(
        session,
        job,
        item,
        importable_files,
        resolved_series_id=resolved_series_id,
        ingest_policy=ingest_policy,
    )
    if plan is None:
        return False

    series = await session.get(Series, plan.series_id)
    if series is not None:
        series.path = str(plan.target_folder)
        series.library_root_id = plan.root.id

    await _rewrite_imported_file_paths_for_adopted_folder(
        session,
        item,
        source_folder=plan.source_folder,
        target_folder=plan.target_folder,
    )
    await record_action(
        session,
        job,
        phase="import",
        action_type="series_folder_renamed",
        payload={
            "series_id": plan.series_id,
            "import_series_id": item.id,
            "old_folder_path": str(plan.source_folder),
            "new_folder_path": str(plan.target_folder),
            "old_series_path": plan.old_series_path or "",
            "old_library_root_id": plan.old_library_root_id,
        },
    )
    await log_event(
        session,
        job.id,
        "INFO",
        "import_series_folder_adopted",
        message=f"Renamed source folder for import: {item.raw_series_name}",
        raw_series_name=item.raw_series_name,
        series_id=plan.series_id,
        old_folder_path=str(plan.source_folder),
        new_folder_path=str(plan.target_folder),
    )
    await session.flush()
    await asyncio.to_thread(plan.target_folder.parent.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(_remove_empty_target_folder_if_present, plan.target_folder)
    await asyncio.to_thread(plan.source_folder.rename, plan.target_folder)
    await session.commit()
    return True


def _folder_adoption_enabled(job: ImportJob, ingest_policy: LibraryIngestPolicy) -> bool:
    if not job.move_to_library:
        return False
    if str(job.transfer_method or "").lower() != "move":
        return False
    return bool(getattr(ingest_policy, "rename_on_import", False))


def _source_folder_for_item(
    item: ImportedSeries,
    importable_files: list[ImportedFile],
) -> Path | None:
    if item.source_folder:
        return Path(item.source_folder)

    parent_paths = {Path(imp_file.file_path).parent for imp_file in importable_files}
    if len(parent_paths) != 1:
        return None
    return next(iter(parent_paths))


def _target_folder_for_series(
    series: Series,
    root: LibraryRoot,
    ingest_policy: LibraryIngestPolicy,
) -> Path:
    if series.path:
        return Path(series.path)
    return Path(root.path) / build_series_folder_name(series, ingest_policy)


def _target_folder_has_blocking_content(target_folder: Path) -> bool:
    """Return true when an existing target would be unsafe to adopt into."""
    if not target_folder.exists():
        return False
    if not target_folder.is_dir():
        return True
    try:
        next(target_folder.iterdir())
    except StopIteration:
        return False
    except OSError:
        return True
    return True


def _remove_empty_target_folder_if_present(target_folder: Path) -> None:
    """Remove an empty pre-created target folder before an atomic source rename."""
    if not target_folder.exists():
        return
    if not target_folder.is_dir():
        raise FileExistsError(f"Target path exists and is not a directory: {target_folder}")
    try:
        target_folder.rmdir()
    except OSError as exc:
        raise FileExistsError(
            f"Target folder is not empty and cannot be adopted into: {target_folder}"
        ) from exc


def _resolved_path(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _path_is_inside_folder(path: Path, folder: Path) -> bool:
    resolved_path = _resolved_path(path)
    resolved_folder = _resolved_path(folder)
    return resolved_path == resolved_folder or resolved_path.is_relative_to(resolved_folder)


def _all_importable_files_are_inside_source(
    source_folder: Path,
    importable_files: list[ImportedFile],
) -> bool:
    return all(
        _path_is_inside_folder(Path(imp_file.file_path), source_folder)
        for imp_file in importable_files
    )


async def _source_folder_is_shared_by_other_review_rows(
    session: AsyncSession,
    job: ImportJob,
    item: ImportedSeries,
    source_folder: Path,
) -> bool:
    result = await session.execute(
        sa_select(ImportedSeries.id).where(
            ImportedSeries.import_job_id == job.id,
            ImportedSeries.id != item.id,
            ImportedSeries.source_folder == str(source_folder),
        )
    )
    return result.first() is not None


async def _source_folder_has_imported_files_for_other_rows(
    session: AsyncSession,
    job: ImportJob,
    item: ImportedSeries,
    source_folder: Path,
) -> bool:
    prefix = str(source_folder)
    result = await session.execute(
        sa_select(ImportedFile.import_series_id, ImportedFile.file_path).where(
            ImportedFile.import_job_id == job.id,
            ImportedFile.file_path.like(f"{prefix}%"),
        )
    )
    for import_series_id, file_path in result.all():
        if not _path_is_inside_folder(Path(str(file_path)), source_folder):
            continue
        if int(import_series_id) != int(item.id):
            return True
    return False


async def _rewrite_imported_file_paths_for_adopted_folder(
    session: AsyncSession,
    item: ImportedSeries,
    *,
    source_folder: Path,
    target_folder: Path,
) -> None:
    result = await session.execute(
        sa_select(ImportedFile).where(ImportedFile.import_series_id == item.id)
    )
    for imp_file in result.scalars().all():
        current_path = Path(imp_file.file_path)
        if not _path_is_inside_folder(current_path, source_folder):
            continue
        relative_path = _resolved_path(current_path).relative_to(_resolved_path(source_folder))
        new_path = target_folder / relative_path
        imp_file.file_path = str(new_path)
