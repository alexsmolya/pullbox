"""Tests for import progress snapshot hydration helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from pullbox.models.import_job import ImportControlRequest, ImportJobStatus


def _job(status: ImportJobStatus, **overrides: object) -> SimpleNamespace:
    defaults: dict[str, object] = {
        "id": 99,
        "status": status,
        "progress_snapshot": {},
        "progress_revision": 4,
        "control_request": ImportControlRequest.NONE,
        "error_message": None,
        "scan_total_files": 10,
        "scan_total_dirs": 2,
        "series_found": 3,
        "series_duplicate": 0,
        "series_matched": 2,
        "series_no_match": 1,
        "series_new": 1,
        "series_imported": 0,
        "series_failed": 0,
        "total_files_found": 10,
        "total_files_matched": 7,
        "total_files_duplicate": 1,
        "total_files_already_owned": 1,
        "total_files_conflict": 0,
        "total_files_no_match": 1,
        "total_files_imported": 0,
        "total_files_failed": 0,
        "scan_started_at": datetime(2026, 6, 6, 12, 0, tzinfo=UTC),
        "import_started_at": None,
        "transfer_method": "move",
        "convert_to_preferred_format": True,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_import_progress_snapshot_terminal_review_overrides_stale_snapshot() -> None:
    from pullbox.ui.import_progress_snapshot import build_import_progress_snapshot

    job = _job(
        ImportJobStatus.REVIEW,
        progress_snapshot={
            "phase": "matching",
            "progress": 45,
            "message": "Still matching...",
            "progress_revision": 2,
            "current_series": "Absolute Superman",
        },
    )
    log_time = datetime(2026, 6, 6, 12, 5, tzinfo=UTC)

    snapshot = build_import_progress_snapshot(
        job,
        review_summary={"ready": 2},
        recent_logs=[
            SimpleNamespace(logged_at=log_time, level="INFO", message="Ready for review"),
        ],
        progress_revision=9,
    )

    assert snapshot["phase"] == "review"
    assert snapshot["progress"] == 100
    assert snapshot["message"] == "Ready for review"
    assert snapshot["progress_revision"] == 9
    assert snapshot["current_series_name"] == "Absolute Superman"
    assert snapshot["review_summary"] == {"ready": 2}
    assert snapshot["recent_logs"] == [
        {
            "logged_at": log_time.isoformat(),
            "level": "INFO",
            "message": "Ready for review",
        }
    ]
    assert snapshot["control_state"]["can_resume"] is True


def test_import_progress_snapshot_paused_import_uses_mode_specific_message() -> None:
    from pullbox.ui.import_progress_snapshot import build_import_progress_snapshot

    job = _job(
        ImportJobStatus.PAUSED,
        import_started_at=datetime(2026, 6, 6, 12, 1, tzinfo=UTC),
        progress_snapshot={
            "mode": "import",
            "phase": "importing",
            "progress": 64,
            "current_file_name": "Fearscape Vol 02.pdf",
        },
    )

    snapshot = build_import_progress_snapshot(
        job,
        review_summary={},
        recent_logs=[],
        progress_revision=5,
    )

    assert snapshot["mode"] == "import"
    assert snapshot["phase"] == "importing"
    assert snapshot["progress"] == 64
    assert snapshot["message"] == "Import is paused."
    assert snapshot["current_file_name"] == "Fearscape Vol 02.pdf"
    assert snapshot["control_state"]["can_resume"] is True


def test_import_progress_snapshot_completed_overrides_stale_progress() -> None:
    from pullbox.ui.import_progress_snapshot import build_import_progress_snapshot

    job = _job(
        ImportJobStatus.COMPLETED,
        import_started_at=datetime(2026, 6, 6, 12, 1, tzinfo=UTC),
        progress_snapshot={
            "mode": "import",
            "phase": "importing",
            "progress": 74,
            "message": "Preparing...",
        },
    )

    snapshot = build_import_progress_snapshot(
        job,
        review_summary={},
        recent_logs=[],
        progress_revision=6,
    )

    assert snapshot["mode"] == "import"
    assert snapshot["phase"] == "done"
    assert snapshot["progress"] == 100
    assert snapshot["message"] == "Import complete."
    assert snapshot["control_state"]["can_view_results"] is True
