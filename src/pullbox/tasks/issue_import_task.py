"""Background runner and live progress state for manual issue imports."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import structlog

from pullbox.core.file_safety import classify_resource_safety_exception
from pullbox.database import get_session_factory
from pullbox.schemas.issue import ManualFileImportProgressResponse, ManualFileImportRequest
from pullbox.services.import_job_execution import calculate_import_file_progress_pct
from pullbox.services.issue_import_service import (
    ManualIssueImportError,
    execute_manual_issue_import,
    prepare_manual_issue_import,
)

logger = structlog.get_logger(__name__)

_issue_import_states: dict[int, ManualFileImportProgressResponse] = {}
_issue_import_start_lock = asyncio.Lock()
_background_tasks: set[asyncio.Task[Any]] = set()


def get_issue_import_progress_state(
    issue_id: int,
) -> ManualFileImportProgressResponse | None:
    """Return the latest in-memory progress snapshot for one issue import."""
    return _issue_import_states.get(issue_id)


async def start_issue_import_run(
    issue_id: int,
    request: ManualFileImportRequest,
) -> ManualFileImportProgressResponse:
    """Start a background manual-import run unless one is already active."""
    async with _issue_import_start_lock:
        existing = _issue_import_states.get(issue_id)
        if existing is not None and existing.state == "running":
            return existing

        initial = ManualFileImportProgressResponse(
            issue_id=issue_id,
            state="running",
            message="Preparing import...",
            current_file_name=Path(request.file_path).name or request.file_path,
            current_file_stage="preparing",
            current_file_progress_pct=0,
            file_index=1,
            total_files=1,
        )
        _issue_import_states[issue_id] = initial

        task = asyncio.create_task(_run_issue_import(issue_id, request.model_dump(mode="python")))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
        return initial


def _set_issue_import_state(
    issue_id: int,
    **updates: Any,
) -> ManualFileImportProgressResponse:
    current = _issue_import_states.get(
        issue_id,
        ManualFileImportProgressResponse(issue_id=issue_id),
    )
    next_state = current.model_copy(update=updates)
    _issue_import_states[issue_id] = next_state
    return next_state


async def _run_issue_import(issue_id: int, request_payload: dict[str, Any]) -> None:
    session_factory = get_session_factory()
    request = ManualFileImportRequest.model_validate(request_payload)
    loop = asyncio.get_running_loop()
    loop_thread_id = threading.get_ident()

    async with session_factory() as session:
        try:
            prepared = await prepare_manual_issue_import(
                session,
                issue_id=issue_id,
                file_path=request.file_path,
                move_to_library=request.move_to_library,
            )
            progress_settings = {
                "move_to_library": True,
                "convert_to_preferred_format": bool(
                    prepared.ingest_policy.normalize_imported_archives_to_cbz
                ),
                "update_embedded_comicinfo_from_match": bool(
                    prepared.ingest_policy.update_embedded_comicinfo_from_match
                ),
            }
            progress_imp_file = SimpleNamespace(file_path=str(prepared.source_path))

            def apply_stage_progress(
                stage: str,
                current: int,
                total: int,
                unit: str,
            ) -> None:
                pct = calculate_import_file_progress_pct(
                    move_to_library=progress_settings["move_to_library"],
                    convert_to_preferred_format=progress_settings["convert_to_preferred_format"],
                    update_embedded_comicinfo_from_match=progress_settings[
                        "update_embedded_comicinfo_from_match"
                    ],
                    imp_file=progress_imp_file,
                    stage=stage,
                    current=current,
                    total=total,
                )
                _set_issue_import_state(
                    issue_id,
                    state="running",
                    message="Importing selected file...",
                    current_file_name=prepared.source_path.name,
                    current_file_stage=stage,
                    current_file_progress_current=current,
                    current_file_progress_total=total,
                    current_file_progress_pct=pct,
                    current_file_progress_unit=unit,
                    file_index=1,
                    total_files=1,
                )

            def emit_stage_progress(
                stage: str,
                current: int,
                total: int,
                unit: str,
            ) -> None:
                if threading.get_ident() == loop_thread_id:
                    apply_stage_progress(stage, current, total, unit)
                    return
                loop.call_soon_threadsafe(apply_stage_progress, stage, current, total, unit)

            _set_issue_import_state(
                issue_id,
                state="running",
                message="Preparing selected file...",
                current_file_name=prepared.source_path.name,
                current_file_stage="preparing",
                current_file_progress_current=0,
                current_file_progress_total=1,
                current_file_progress_pct=0,
                current_file_progress_unit="steps",
                file_index=1,
                total_files=1,
            )

            result = await execute_manual_issue_import(
                session,
                prepared,
                allow_resource_safety_exception=request.allow_resource_safety_exception,
                preparation_progress_callback=emit_stage_progress,
                transfer_progress_callback=lambda current, total: emit_stage_progress(
                    stage="transferring",
                    current=current,
                    total=total,
                    unit="bytes",
                ),
                comicinfo_progress_callback=lambda stage, current, total, unit: emit_stage_progress(
                    stage=stage,
                    current=current,
                    total=total,
                    unit=unit,
                ),
            )
            await session.commit()
            _set_issue_import_state(
                issue_id,
                state="completed",
                message="Import complete.",
                current_file_name=result.library_file.file_name,
                current_file_stage="finalizing",
                current_file_progress_current=1,
                current_file_progress_total=1,
                current_file_progress_pct=100,
                current_file_progress_unit="steps",
                file_index=1,
                total_files=1,
                library_file_id=result.library_file.id,
                file_name=result.library_file.file_name,
                file_path=result.library_file.file_path,
                file_size=result.library_file.file_size,
                file_format=(
                    result.library_file.file_format.value
                    if hasattr(result.library_file.file_format, "value")
                    else str(result.library_file.file_format)
                ),
                match_confidence=(
                    result.library_file.match_confidence.value
                    if hasattr(result.library_file.match_confidence, "value")
                    else str(result.library_file.match_confidence)
                ),
                error_message=None,
            )
        except (ManualIssueImportError, FileNotFoundError) as exc:
            await session.rollback()
            _set_issue_import_state(
                issue_id,
                state="failed",
                message="Import failed.",
                error_message=str(getattr(exc, "detail", exc)),
                current_file_stage=None,
                current_file_progress_current=None,
                current_file_progress_total=None,
                current_file_progress_pct=None,
                current_file_progress_unit=None,
            )
        except Exception as exc:
            logger.exception("issue_import_run_failed", issue_id=issue_id)
            await session.rollback()
            resource_block = classify_resource_safety_exception(exc)
            if resource_block is not None:
                _set_issue_import_state(
                    issue_id,
                    state="safety_blocked",
                    message="Safety approval required.",
                    error_message=resource_block.reason,
                    safety_exception=resource_block.to_diagnostics(),
                    current_file_stage=None,
                    current_file_progress_current=None,
                    current_file_progress_total=None,
                    current_file_progress_pct=None,
                    current_file_progress_unit=None,
                )
                return
            _set_issue_import_state(
                issue_id,
                state="failed",
                message="Import failed.",
                error_message=str(exc),
                current_file_stage=None,
                current_file_progress_current=None,
                current_file_progress_total=None,
                current_file_progress_pct=None,
                current_file_progress_unit=None,
            )
