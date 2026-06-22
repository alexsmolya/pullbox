"""Import rollback journal action helpers."""

from __future__ import annotations

import contextlib
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from sqlalchemy import func as sa_func
from sqlalchemy import select as sa_select

from pullbox.core.exceptions import NotFoundError
from pullbox.models.import_job import (
    ImportJob,
    ImportJobAction,
    ImportJobActionStatus,
)
from pullbox.models.library import LibraryFile
from pullbox.models.series import Series
from pullbox.utilities.settings import restore_file_from_utility_trash

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class DeleteSeriesForRollback(Protocol):
    """Callable used to remove a series created by an import action."""

    async def __call__(
        self,
        session: AsyncSession,
        series_id: int,
        *,
        delete_files: bool,
        delete_folder: bool,
    ) -> None: ...


async def next_action_sequence(session: AsyncSession, job_id: int) -> int:
    """Return the next durable action sequence number for a job."""
    max_seq = await session.scalar(
        sa_select(sa_func.max(ImportJobAction.sequence_no)).where(
            ImportJobAction.import_job_id == job_id
        )
    )
    return int(max_seq or 0) + 1


async def record_action(
    session: AsyncSession,
    job: ImportJob,
    *,
    phase: str,
    action_type: str,
    payload: dict[str, Any],
) -> ImportJobAction:
    """Persist a durable rollback journal action."""
    action = ImportJobAction(
        import_job_id=job.id,
        sequence_no=await next_action_sequence(session, job.id),
        phase=phase,
        action_type=action_type,
        status=ImportJobActionStatus.COMPLETED,
        payload=payload,
    )
    session.add(action)
    await session.flush()
    return action


async def rollback_action(
    session: AsyncSession,
    *,
    action_id: int,
    action_type: str,
    payload: dict[str, Any],
    delete_series: DeleteSeriesForRollback,
) -> None:
    """Reverse a recorded import action in reverse execution order."""
    if action_type == "library_file_registered":
        library_file_id = int(payload.get("library_file_id") or 0)
        destination_path = Path(str(payload.get("destination_path") or ""))
        original_source_path = Path(str(payload.get("original_source_path") or ""))
        transfer_method = str(payload.get("transfer_method") or "move")
        original_trash_path = str(payload.get("original_trash_path") or "")
        created_series_folder = bool(payload.get("created_series_folder"))
        created_series_folder_path_raw = str(payload.get("created_series_folder_path") or "")
        permission_restores = list(payload.get("permission_restores") or [])

        library_file = await session.get(LibraryFile, library_file_id)
        if library_file is not None:
            await session.delete(library_file)

        if transfer_method in {"move", "leave_in_place"}:
            if original_trash_path:
                restore_file_from_utility_trash(Path(original_trash_path), original_source_path)
                if destination_path.exists():
                    destination_path.unlink(missing_ok=True)
            elif destination_path.exists():
                original_source_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(destination_path), str(original_source_path))
        elif destination_path.exists():
            destination_path.unlink(missing_ok=True)

        for entry in permission_restores:
            restore_path = Path(str(entry.get("path") or ""))
            restore_mode = entry.get("mode")
            if not restore_path or restore_mode is None or not restore_path.exists():
                continue
            try:
                restore_path.chmod(int(restore_mode))
            except OSError:
                continue

        if created_series_folder and created_series_folder_path_raw:
            created_series_folder_path = Path(created_series_folder_path_raw)
        else:
            created_series_folder_path = None

        if created_series_folder_path is not None and created_series_folder_path.exists():
            try:
                next(created_series_folder_path.iterdir())
            except StopIteration:
                created_series_folder_path.rmdir()
            except OSError:
                pass

    elif action_type == "series_created":
        series_id = int(payload.get("series_id") or 0)
        if series_id:
            with contextlib.suppress(NotFoundError):
                await delete_series(
                    session,
                    series_id,
                    delete_files=False,
                    delete_folder=True,
                )
                # A series-created action can be replayed after a partial rollback or
                # after multiple import rows converged on the same real series. Missing
                # here means the rollback objective is already satisfied.

    elif action_type == "series_folder_renamed":
        series_id = int(payload.get("series_id") or 0)
        old_folder_path = Path(str(payload.get("old_folder_path") or ""))
        new_folder_path = Path(str(payload.get("new_folder_path") or ""))
        old_series_path = str(payload.get("old_series_path") or "")
        old_library_root_id_raw = payload.get("old_library_root_id")

        if new_folder_path.exists() and not old_folder_path.exists():
            old_folder_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(new_folder_path), str(old_folder_path))

        if series_id:
            series = await session.get(Series, series_id)
            if series is not None:
                series.path = old_series_path or None
                series.library_root_id = (
                    int(old_library_root_id_raw) if old_library_root_id_raw is not None else None
                )

    action = await session.get(ImportJobAction, action_id)
    if action is None:
        return
    action.status = ImportJobActionStatus.ROLLED_BACK
    action.rolled_back_at = datetime.now(UTC)
    await session.flush()
