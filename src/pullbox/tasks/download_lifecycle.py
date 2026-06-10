"""Download lifecycle timing and post-processing classification helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pullbox.models.download import DownloadHistory


def compute_download_lifecycle_duration(
    download: DownloadHistory,
    *,
    observed_at: datetime | None,
) -> tuple[float | None, str | None]:
    """Return the best available lifecycle duration and its basis."""
    now = datetime.now(UTC)
    if download.sent_at is not None:
        return (max(0.0, (now - download.sent_at).total_seconds() * 1000), "sent_at")
    if observed_at is not None:
        return (max(0.0, (now - observed_at).total_seconds() * 1000), "first_observed")
    return (None, None)


def download_lifecycle_summary_payload(
    download: DownloadHistory,
    *,
    outcome: str,
    client_state: str | None,
    downloaded_path: str | None,
    observed_at: datetime | None,
) -> dict[str, object]:
    """Return the structured fields for a terminal download lifecycle log."""
    duration_ms, duration_basis = compute_download_lifecycle_duration(
        download,
        observed_at=observed_at,
    )
    return {
        "download_id": download.id,
        "issue_id": download.issue_id,
        "external_id": download.external_id,
        "download_client": str(download.download_client.value),
        "outcome": outcome,
        "final_state": str(download.state.value),
        "final_client_state": client_state,
        "downloaded_path": downloaded_path,
        "retry_count": download.retry_count,
        "max_retries": download.max_retries,
        "next_retry_at": str(download.next_retry_at) if download.next_retry_at else None,
        "error_message": download.error_message,
        "lifecycle_duration_ms": round(duration_ms, 1) if duration_ms is not None else None,
        "duration_basis": duration_basis,
    }


def classify_post_processing_error(exc: Exception) -> str:
    """Classify post-processing failures for troubleshooting summaries."""
    if isinstance(exc, FileNotFoundError):
        lowered = str(exc).lower()
        if "quick integrity check" in lowered or "unreadable" in lowered:
            return "source_unreadable"
        if "did not become visible" in lowered:
            return "source_visibility"
        return "path_not_found"
    if isinstance(exc, RuntimeError):
        message = str(exc)
        if message.startswith("Release failed quick integrity check"):
            return "bad_release"
        if message.startswith("File safety:"):
            return "file_safety"
        return "runtime_error"
    return "unexpected"
