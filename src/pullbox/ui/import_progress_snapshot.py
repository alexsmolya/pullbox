"""Import progress snapshot hydration for UI routes."""

from __future__ import annotations

from typing import Any, cast

from pullbox.models.import_job import ImportJobStatus
from pullbox.services.import_workflow_state import (
    WORKFLOW_SNAPSHOT_VERSION,
    import_control_state_for_job,
    paused_message_for_mode,
    snapshot_mode_for_job,
    snapshot_requested_action_for_job,
    stalled_message,
)

_PROGRESS_FALLBACK_BY_STATUS = {
    ImportJobStatus.SCANNING: 10,
    ImportJobStatus.ANALYZING: 35,
    ImportJobStatus.MATCHING: 45,
    ImportJobStatus.FILE_MATCHING: 80,
    ImportJobStatus.IMPORTING: 5,
    ImportJobStatus.STALLED: 0,
    ImportJobStatus.ROLLING_BACK: 5,
    ImportJobStatus.REVIEW: 100,
    ImportJobStatus.COMPLETED: 100,
    ImportJobStatus.CANCELLED: 100,
    ImportJobStatus.FAILED: 100,
    ImportJobStatus.ROLLED_BACK: 100,
}

_MESSAGE_FALLBACK_BY_STATUS = {
    ImportJobStatus.REVIEW: "Ready for review",
    ImportJobStatus.COMPLETED: "Import complete.",
    ImportJobStatus.ROLLED_BACK: "Import rollback completed.",
    ImportJobStatus.ROLLING_BACK: "Rolling back import actions...",
    ImportJobStatus.IMPORTING: "Preparing the selected series for import...",
    ImportJobStatus.SCANNING: "Scanning your collection...",
    ImportJobStatus.ANALYZING: "Analyzing for duplicates...",
    ImportJobStatus.MATCHING: "Matching against ComicVine...",
    ImportJobStatus.FILE_MATCHING: "Matching files to issues...",
    ImportJobStatus.STALLED: stalled_message(),
}


def _object_to_int(value: object, default: int = 0) -> int:
    try:
        return int(cast("Any", value))
    except (TypeError, ValueError):
        return default


def _fallback_phase(job: Any, effective_mode: str, snapshot: dict[str, object]) -> str:
    phase_value = str(snapshot.get("phase") or "")
    if phase_value:
        return phase_value
    if effective_mode == "rollback":
        return "rollback" if job.status != ImportJobStatus.ROLLED_BACK else "done"
    if effective_mode == "import":
        if job.status in {
            ImportJobStatus.COMPLETED,
            ImportJobStatus.CANCELLED,
            ImportJobStatus.FAILED,
        }:
            return "done"
        if job.status == ImportJobStatus.IMPORTING:
            return "importing"
        return "queued"
    if job.status == ImportJobStatus.REVIEW:
        return "review"
    if job.status == ImportJobStatus.FILE_MATCHING:
        return "file_matching"
    if job.status == ImportJobStatus.MATCHING:
        return "matching"
    if job.status == ImportJobStatus.ANALYZING:
        return "analyzing"
    if job.status == ImportJobStatus.SCANNING:
        return "scanning"
    if job.status == ImportJobStatus.PAUSED:
        return str(snapshot.get("phase") or "scanning")
    return "inventory"


def _fallback_message(job: Any, effective_mode: str, snapshot: dict[str, object]) -> str:
    message_value = str(snapshot.get("message") or "")
    if message_value:
        return message_value
    if job.status == ImportJobStatus.CANCELLED:
        return job.error_message or "Import cancelled by user."
    if job.status == ImportJobStatus.FAILED:
        return job.error_message or "Import failed."
    if job.status == ImportJobStatus.PAUSED:
        return paused_message_for_mode(effective_mode)
    if job.status == ImportJobStatus.STALLED:
        return job.error_message or stalled_message()
    return _MESSAGE_FALLBACK_BY_STATUS.get(job.status, "Preparing scan inventory...")


def _terminal_snapshot_values(job: Any) -> tuple[str, int, str] | None:
    if job.status == ImportJobStatus.REVIEW:
        return "review", 100, "Ready for review"
    if job.status == ImportJobStatus.COMPLETED:
        return "done", 100, "Import complete."
    if job.status == ImportJobStatus.ROLLED_BACK:
        return "rollback", 100, "Import rollback completed."
    if job.status == ImportJobStatus.CANCELLED:
        return "done", 100, job.error_message or "Import cancelled by user."
    if job.status == ImportJobStatus.FAILED:
        return "done", 100, job.error_message or "Import failed."
    return None


def build_import_progress_snapshot(
    job: Any,
    *,
    review_summary: dict[str, int],
    recent_logs: list[Any],
    progress_revision: int,
) -> dict[str, object]:
    """Build the durable Step 2/4 snapshot for progress hydration."""
    snapshot: dict[str, object] = dict(job.progress_snapshot or {})
    effective_mode = snapshot_mode_for_job(job)
    progress_value = snapshot.get("progress")
    if not isinstance(progress_value, int):
        progress_value = _PROGRESS_FALLBACK_BY_STATUS.get(job.status, 0)
    phase_value = _fallback_phase(job, effective_mode, snapshot)
    message_value = _fallback_message(job, effective_mode, snapshot)

    terminal_values = _terminal_snapshot_values(job)
    if terminal_values is not None:
        phase_value, progress_value, message_value = terminal_values

    snapshot.update(
        {
            "snapshot_version": _object_to_int(
                snapshot.get("snapshot_version"),
                WORKFLOW_SNAPSHOT_VERSION,
            ),
            "job_id": job.id,
            "status": job.status.value,
            "mode": effective_mode,
            "phase": phase_value,
            "progress": progress_value,
            "message": message_value,
            "requested_action": snapshot_requested_action_for_job(job).value,
            "progress_revision": progress_revision,
            "last_checkpoint_at": snapshot.get("last_checkpoint_at"),
            "current_series_id": snapshot.get("current_series_id"),
            "current_series_name": snapshot.get("current_series_name")
            or snapshot.get("current_series"),
            "current_file_id": snapshot.get("current_file_id"),
            "current_file_name": snapshot.get("current_file_name"),
            "current_file_stage": snapshot.get("current_file_stage"),
            "current_file_progress_current": snapshot.get("current_file_progress_current"),
            "current_file_progress_total": snapshot.get("current_file_progress_total"),
            "current_file_progress_pct": snapshot.get("current_file_progress_pct"),
            "current_file_progress_unit": snapshot.get("current_file_progress_unit"),
            "current_series": snapshot.get("current_series") or snapshot.get("current_series_name"),
            "error_message": job.error_message,
            "scan_total_files": job.scan_total_files,
            "scan_total_dirs": job.scan_total_dirs,
            "series_found": job.series_found,
            "series_duplicate": job.series_duplicate,
            "series_matched": job.series_matched,
            "series_no_match": job.series_no_match,
            "series_new": job.series_new,
            "series_imported": job.series_imported,
            "series_failed": job.series_failed,
            "total_files_found": job.total_files_found,
            "total_files_matched": job.total_files_matched,
            "total_files_duplicate": job.total_files_duplicate,
            "total_files_already_owned": job.total_files_already_owned,
            "total_files_conflict": job.total_files_conflict,
            "total_files_no_match": job.total_files_no_match,
            "total_files_imported": job.total_files_imported,
            "total_files_failed": job.total_files_failed,
            "review_summary": review_summary,
            "scan_started_at": job.scan_started_at.isoformat() if job.scan_started_at else None,
            "import_started_at": job.import_started_at.isoformat()
            if job.import_started_at
            else None,
            "recent_logs": [
                {
                    "logged_at": log.logged_at.isoformat(),
                    "level": log.level,
                    "message": log.message or "",
                }
                for log in recent_logs
            ],
            "control_state": import_control_state_for_job(job),
        }
    )
    return snapshot
