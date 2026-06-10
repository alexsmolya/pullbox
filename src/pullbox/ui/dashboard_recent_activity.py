"""Dashboard recent-activity presenter helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pullbox.models.download import DownloadClientType
from pullbox.models.import_job import ImportJobStatus
from pullbox.ui.dashboard_display import dashboard_relative_time_label

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from pullbox.models.download import DownloadHistory
    from pullbox.models.import_job import ImportJob


@dataclass(frozen=True)
class DashboardRecentActivityItemView:
    """Recent activity feed row."""

    key: str
    kind: str
    summary: str
    detail: str
    time_label: str
    href: str


def build_download_recent_activity_item(
    download: DownloadHistory,
    current_time: datetime,
    *,
    format_issue_number: Callable[[float], str],
    download_client_label: Callable[[str], str],
) -> tuple[datetime, DashboardRecentActivityItemView] | None:
    """Build a dashboard recent-activity item for a terminal download row."""
    when = download.imported_at or download.completed_at or download.updated_at
    if when is None:
        return None

    if download.issue is not None and download.issue.series is not None:
        issue_label = (
            f"{download.issue.series.title} #{format_issue_number(download.issue.issue_number)}"
        )
    else:
        issue_label = download.title

    client_value = (
        download.download_client.value
        if isinstance(download.download_client, DownloadClientType)
        else str(download.download_client)
    )
    client_label = download_client_label(client_value)
    detail = (
        f"Imported via {client_label}."
        if download.imported_at is not None
        else f"Download completed via {client_label}."
    )

    return (
        when,
        DashboardRecentActivityItemView(
            key=f"download-{download.id}",
            kind="acquired",
            summary=issue_label,
            detail=detail,
            time_label=dashboard_relative_time_label(when, current_time),
            href="/downloads?tab=history",
        ),
    )


def build_import_recent_activity_item(
    job: ImportJob,
    current_time: datetime,
) -> tuple[datetime, DashboardRecentActivityItemView] | None:
    """Build a dashboard recent-activity item for a terminal import job."""
    when = job.import_completed_at or job.updated_at
    if when is None:
        return None

    if job.status == ImportJobStatus.COMPLETED:
        kind = "imported"
        summary = "Import run completed."
        detail = (
            f"{job.total_files_imported} file"
            f"{'' if job.total_files_imported == 1 else 's'} imported."
        )
    else:
        kind = "failed"
        summary = "Import run failed."
        detail = (
            f"{job.total_files_failed} file action"
            f"{'' if job.total_files_failed == 1 else 's'} failed."
        )

    return (
        when,
        DashboardRecentActivityItemView(
            key=f"import-{job.id}",
            kind=kind,
            summary=summary,
            detail=detail,
            time_label=dashboard_relative_time_label(when, current_time),
            href="/import?tab=history",
        ),
    )
