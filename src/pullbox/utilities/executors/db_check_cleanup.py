"""Database check & cleanup executor — detect and fix data integrity issues.

Two-phase operation: preview (read-only detection) then execute
(user-selected actions). Detects orphaned records (DB pointing to
missing files), stale files (on disk but not in DB), path/root drift,
and metadata refresh work for tracked library files.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import select

from pullbox.core.filesystem_scan import iter_supported_files
from pullbox.models.library import LibraryRoot
from pullbox.services.db_check_service import apply_db_check_repair, register_stale_library_file
from pullbox.utilities.base_executor import (
    ApplyResult,
    ExecutionMode,
    FinalizeResult,
    ItemResult,
    JobExecutor,
    JobRunSummary,
    ProcessedItem,
    RuntimeLogEntry,
)

logger = structlog.get_logger(__name__)

_COMIC_EXTENSIONS = frozenset({".cbz", ".cbr", ".cb7", ".cbt", ".pdf", ".epub"})

_VALID_CHECKS = frozenset({"orphans", "stale", "referential", "reindex", "optimize"})
_IGNORED_STALE_DIR_NAMES = frozenset({".trash"})


# ── Detection Functions (standalone, testable) ─────────────────


def detect_orphaned_records(
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Find DB records whose file_path points to a nonexistent file.

    Records with NULL or empty file_path are excluded (valid for
    wanted/missing issues that don't have files yet).

    Args:
        records: List of dicts with 'id' and 'file_path' keys.

    Returns:
        List of record dicts where the file is missing from disk.
    """
    orphans: list[dict[str, Any]] = []
    for record in records:
        file_path = record.get("file_path")
        if not file_path:
            continue
        if not Path(file_path).exists():
            orphans.append(record)
    return orphans


def detect_stale_files(
    library_root: Path,
    known_paths: set[str],
) -> list[dict[str, Any]]:
    """Find comic files on disk that are not tracked in the database.

    Only files with comic extensions (.cbz, .cbr, etc.) are checked.
    Non-comic files (readme.txt, cover.jpg, etc.) are ignored.

    Args:
        library_root: Root directory to scan.
        known_paths: Set of file paths tracked in the database.

    Returns:
        List of dicts with 'path' and 'size' for each stale file.
    """
    if not library_root.exists():
        return []

    stale: list[dict[str, Any]] = []
    for path in iter_supported_files(library_root, _COMIC_EXTENSIONS):
        try:
            relative_parts = path.relative_to(library_root).parts[:-1]
        except ValueError:
            relative_parts = ()
        if any(part.lower() in _IGNORED_STALE_DIR_NAMES for part in relative_parts):
            continue
        if str(path) not in known_paths:
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            stale.append({"path": str(path), "size": size})
    return stale


# ── Executor ───────────────────────────────────────────────────


class DBCheckCleanupExecutor(JobExecutor):
    """Two-phase executor: preview detects issues, execute applies fixes.

    Config keys:
        checks: List of check types to run (orphans, stale, referential, reindex)
        mode: "preview" (read-only) or "execute" (apply actions)
        library_root: Path to library root (for stale file detection)
    """

    execution_mode = ExecutionMode.SERIAL

    def validate_config(self, job_config: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        checks = job_config.get("checks")
        if not checks:
            errors.append("checks is required (list of check types)")
        elif isinstance(checks, list):
            for check in checks:
                if check not in _VALID_CHECKS:
                    errors.append(
                        f"Unknown check type: {check}. Valid: {', '.join(sorted(_VALID_CHECKS))}"
                    )
        return errors

    async def generate_items(
        self,
        job_config: dict[str, Any],
        job_context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Generate check items based on configured checks.

        Preview already builds a concrete set of actions, so the queued
        execution phase simply persists that action list as job items.
        """
        actions = job_config.get("actions", [])
        items: list[dict[str, Any]] = []
        for action in actions:
            items.append(
                {
                    "file_path": action.get("file_path"),
                    "operation": action.get("operation", "check"),
                    "record_id": action.get("record_id"),
                    "record_type": action.get("record_type"),
                    "description": action.get("description", ""),
                    "context": action.get("context") or {},
                }
            )
        return items

    def process_item(
        self,
        item_data: dict[str, Any],
        job_config: dict[str, Any],
        job_context: dict[str, Any] | None = None,
    ) -> ProcessedItem:
        """Execute or preview a single cleanup action."""
        start = time.monotonic()
        item_id = item_data.get("id", "unknown")
        operation = item_data.get("operation", "check")
        mode = job_config.get("mode", "preview")

        try:
            # Skip actions in preview mode
            if mode == "preview":
                return ProcessedItem(
                    item_id=item_id,
                    result=ItemResult.SKIPPED,
                    before_state=item_data,
                    duration_ms=int((time.monotonic() - start) * 1000),
                    log_entries=[
                        ("INFO", f"Preview: {operation} — {item_data.get('description', '')}", {}),
                    ],
                )

            # Skip explicitly skipped items
            if operation == "skip":
                return ProcessedItem(
                    item_id=item_id,
                    result=ItemResult.SKIPPED,
                    duration_ms=int((time.monotonic() - start) * 1000),
                    log_entries=[("INFO", "Skipped by user", {})],
                )

            # Execute the action
            # In a full implementation, this would modify the DB.
            # For now, we record the action as completed.
            record_type = item_data.get("record_type", "unknown")
            record_id = item_data.get("record_id", "?")
            file_path = item_data.get("file_path", "")
            description = item_data.get("description", "")
            raw_context = item_data.get("context")
            context = raw_context if isinstance(raw_context, dict) else {}
            duration_ms = int((time.monotonic() - start) * 1000)

            log_entries: list[tuple[str, str, dict[str, Any]]] = []

            # Summary log entry
            if operation == "delete":
                log_entries.append(
                    (
                        "INFO",
                        f"Deleted {record_type} #{record_id}"
                        + (f": {file_path}" if file_path else ""),
                        {"record_type": record_type, "record_id": record_id},
                    )
                )
            elif operation == "add":
                log_entries.append(
                    (
                        "INFO",
                        f"Registered {record_type}" + (f": {file_path}" if file_path else ""),
                        {"record_type": record_type},
                    )
                )
            elif operation == "repair":
                log_entries.append(
                    (
                        "INFO",
                        f"Repaired {record_type}" + (f": {file_path}" if file_path else ""),
                        {
                            "record_type": record_type,
                            "repair_kind": context.get("repair_kind"),
                        },
                    )
                )
            elif operation == "reindex":
                log_entries.append(
                    (
                        "INFO",
                        "Metadata refresh completed",
                        {"target_root_path": context.get("target_root_path") or file_path},
                    )
                )
            else:
                log_entries.append(
                    (
                        "INFO",
                        f"Executed {operation} on {record_type} #{record_id}",
                        {},
                    )
                )

            # Debug-level detail
            if description:
                log_entries.append(
                    (
                        "DEBUG",
                        f"Detail: {description}",
                        {"file_path": file_path},
                    )
                )

            return ProcessedItem(
                item_id=item_id,
                result=ItemResult.COMPLETED,
                before_state={
                    "record_id": record_id,
                    "record_type": record_type,
                    "operation": operation,
                    "file_path": file_path,
                    "context": context,
                },
                after_state={"action_taken": operation, "repair_kind": context.get("repair_kind")},
                duration_ms=duration_ms,
                log_entries=log_entries,
            )

        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            return ProcessedItem(
                item_id=item_id,
                result=ItemResult.FAILED,
                duration_ms=duration_ms,
                error_message=str(exc),
                log_entries=[("ERROR", f"Action failed: {exc}", {})],
            )

    def rollback_item(
        self,
        item_data: dict[str, Any],
        job_config: dict[str, Any],
        job_context: dict[str, Any] | None = None,
    ) -> ProcessedItem:
        """Record rollback intent for DB cleanup actions.

        Full DB rollback would re-insert deleted records from before_state.
        For now, records the rollback action.
        """
        start = time.monotonic()
        item_id = item_data.get("id", "unknown")
        duration_ms = int((time.monotonic() - start) * 1000)

        return ProcessedItem(
            item_id=item_id,
            result=ItemResult.COMPLETED,
            duration_ms=duration_ms,
            log_entries=[
                ("INFO", f"Rollback recorded for {item_id}", {}),
            ],
        )

    async def apply_item_result(
        self,
        session: Any,
        item: Any,
        item_data: dict[str, Any],
        processed: ProcessedItem,
        job_config: dict[str, Any],
        job_context: dict[str, Any] | None,
        summary: JobRunSummary,
    ) -> ApplyResult:
        if processed.result != ItemResult.COMPLETED:
            return ApplyResult()

        operation = str(item_data.get("operation", "skip") or "skip")
        record_type = item_data.get("record_type")
        record_id = item_data.get("record_id")
        file_path = str(item_data.get("file_path", "") or "")

        if operation == "skip" or not record_type:
            return ApplyResult()

        if operation == "delete" and record_id is not None and record_type == "library_file":
            from pullbox.models.library import LibraryFile

            obj = await session.get(LibraryFile, record_id)
            if obj is not None:
                await session.delete(obj)
            return ApplyResult()

        unresolved: dict[str, Any] | None = None
        if operation == "add" and record_type == "file" and file_path:
            unresolved = await register_stale_library_file(session, file_path_str=file_path)
        elif operation in {"repair", "reindex"}:
            await apply_db_check_repair(session, item_data)

        if not unresolved:
            return ApplyResult()

        item.warning_message = unresolved.get("reason", "Unresolvable")
        summary.metadata.setdefault("unresolvable", []).append(unresolved)
        return ApplyResult(
            warning_increment=1,
            warning_message=item.warning_message,
            extra_logs=[
                RuntimeLogEntry(
                    level="WARNING",
                    message=f"Unresolvable: {unresolved.get('reason', '')}",
                    file_path=unresolved.get("file_path"),
                    extra=unresolved,
                )
            ],
        )

    async def finalize_job(
        self,
        session: Any,
        job: Any,
        summary: JobRunSummary,
        job_config: dict[str, Any],
        job_context: dict[str, Any] | None,
    ) -> FinalizeResult:
        unresolvable = list(summary.metadata.get("unresolvable", []))
        if not unresolvable:
            return FinalizeResult()

        roots_result = await session.execute(
            select(LibraryRoot.path).where(LibraryRoot.enabled.is_(True))
        )
        root_paths = {row[0] for row in roots_result.all()}

        importable_folders: dict[str, list[str]] = {}
        loose_files: list[str] = []

        for unresolved_item in unresolvable:
            folder = str(unresolved_item.get("folder", "") or "")
            file_path = str(unresolved_item.get("file_path", "") or "")
            if folder in root_paths:
                loose_files.append(file_path)
            else:
                importable_folders.setdefault(folder, []).append(file_path)

        extra_data: dict[str, object] = {}
        msg_parts: list[str] = []
        if importable_folders:
            extra_data["unresolvable_folders"] = importable_folders
            msg_parts.append(
                f"{sum(len(v) for v in importable_folders.values())} files in "
                f"{len(importable_folders)} folders"
            )
        if loose_files:
            extra_data["loose_files"] = loose_files
            msg_parts.append(
                f"{len(loose_files)} loose file{'s' if len(loose_files) != 1 else ''} "
                "in library root"
            )

        job.error_message = (
            f"NEEDS_ATTENTION:{len(unresolvable)} files could not be matched to a series."
        )
        return FinalizeResult(
            extra_logs=[
                RuntimeLogEntry(
                    level="WARNING",
                    message="Unresolvable: " + ", ".join(msg_parts),
                    extra=extra_data,
                )
            ],
            final_parts=[f"{len(unresolvable)} unresolvable"],
            final_log_level="WARNING",
        )
