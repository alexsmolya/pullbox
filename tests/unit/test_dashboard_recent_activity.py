from __future__ import annotations

from datetime import datetime, timedelta

from pullbox.models.download import DownloadClientType, DownloadHistory, DownloadState
from pullbox.models.import_job import ImportJob, ImportJobStatus, ImportSourceType
from pullbox.models.issue import Issue
from pullbox.models.series import Series
from pullbox.ui.dashboard_recent_activity import (
    build_download_recent_activity_item,
    build_import_recent_activity_item,
)


def _issue_number(value: float) -> str:
    return f"{value:g}"


def _client_label(value: str) -> str:
    return {"sabnzbd": "SABnzbd", "transmission": "Transmission"}.get(value, value.title())


def test_build_download_recent_activity_item_prefers_issue_series_label() -> None:
    current_time = datetime(2026, 6, 9, 12, 0, 0)
    download = DownloadHistory(
        id=42,
        issue_id=10,
        title="Fallback title",
        download_url="https://example.invalid/download",
        download_client=DownloadClientType.SABNZBD,
        state=DownloadState.IMPORTED,
        imported_at=current_time - timedelta(minutes=5),
    )
    download.issue = Issue(id=10, series_id=3, issue_number=4.0)
    download.issue.series = Series(id=3, title="Drifter", sort_title="drifter")

    activity = build_download_recent_activity_item(
        download,
        current_time,
        format_issue_number=_issue_number,
        download_client_label=_client_label,
    )

    assert activity is not None
    when, item = activity
    assert when == download.imported_at
    assert item.key == "download-42"
    assert item.kind == "acquired"
    assert item.summary == "Drifter #4"
    assert item.detail == "Imported via SABnzbd."
    assert item.time_label == "5m ago"
    assert item.href == "/downloads?tab=history"


def test_build_download_recent_activity_item_uses_title_when_issue_is_missing() -> None:
    current_time = datetime(2026, 6, 9, 12, 0, 0)
    download = DownloadHistory(
        id=43,
        issue_id=11,
        title="Loose result",
        download_url="https://example.invalid/download",
        download_client=DownloadClientType.TRANSMISSION,
        state=DownloadState.COMPLETED,
        completed_at=current_time - timedelta(hours=2),
    )

    activity = build_download_recent_activity_item(
        download,
        current_time,
        format_issue_number=_issue_number,
        download_client_label=_client_label,
    )

    assert activity is not None
    _when, item = activity
    assert item.summary == "Loose result"
    assert item.detail == "Download completed via Transmission."
    assert item.time_label == "2h ago"


def test_build_import_recent_activity_item_formats_completed_and_failed_jobs() -> None:
    current_time = datetime(2026, 6, 9, 12, 0, 0)
    completed = ImportJob(
        id=7,
        source_path="/imports",
        source_type=ImportSourceType.FILESYSTEM,
        status=ImportJobStatus.COMPLETED,
        total_files_imported=2,
        total_files_failed=0,
        import_completed_at=current_time - timedelta(minutes=30),
    )
    failed = ImportJob(
        id=8,
        source_path="/imports",
        source_type=ImportSourceType.FILESYSTEM,
        status=ImportJobStatus.FAILED,
        total_files_imported=0,
        total_files_failed=1,
        updated_at=current_time - timedelta(days=1),
    )

    completed_activity = build_import_recent_activity_item(completed, current_time)
    failed_activity = build_import_recent_activity_item(failed, current_time)

    assert completed_activity is not None
    assert failed_activity is not None
    _completed_when, completed_item = completed_activity
    _failed_when, failed_item = failed_activity

    assert completed_item.key == "import-7"
    assert completed_item.kind == "imported"
    assert completed_item.summary == "Import run completed."
    assert completed_item.detail == "2 files imported."
    assert completed_item.time_label == "30m ago"
    assert completed_item.href == "/import?tab=history"

    assert failed_item.key == "import-8"
    assert failed_item.kind == "failed"
    assert failed_item.summary == "Import run failed."
    assert failed_item.detail == "1 file action failed."
    assert failed_item.time_label == "1d ago"
    assert failed_item.href == "/import?tab=history"
