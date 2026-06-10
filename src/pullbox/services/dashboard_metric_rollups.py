"""Pure dashboard metric rollup helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pullbox.models.download import DownloadClientType

if TYPE_CHECKING:
    from datetime import datetime

    from pullbox.services.dashboard_types import DashboardSnapshot


DASHBOARD_ROLLUP_KEYS = (
    "active_downloads",
    "review_debt_total",
    "release_risk_count",
    "flow_through_rate",
    "client_reliability_rate",
    "storage_used_percent",
    "search_yield_rate",
    "import_failure_count",
    "unmatched_backlog",
    "health_problem_count",
)

DashboardRollupPayload = dict[str, tuple[float, dict[str, object]]]


def dashboard_download_client_label(client_type: DownloadClientType | str) -> str:
    """Return the user-facing dashboard label for a download client."""
    value = client_type.value if isinstance(client_type, DownloadClientType) else client_type
    labels = {
        DownloadClientType.SABNZBD.value: "SABnzbd",
        DownloadClientType.NZBGET.value: "NZBGet",
        DownloadClientType.QBITTORRENT.value: "qBittorrent",
        DownloadClientType.TRANSMISSION.value: "Transmission",
        DownloadClientType.DELUGE.value: "Deluge",
    }
    return labels.get(value, value.replace("_", " ").title())


def dashboard_hour_bucket_start(current_time: datetime) -> datetime:
    """Truncate a timestamp to the dashboard rollup hour bucket."""
    return current_time.replace(minute=0, second=0, microsecond=0)


def dashboard_rollup_payload(snapshot: DashboardSnapshot) -> DashboardRollupPayload:
    """Build dashboard rollup metric values and context from a snapshot."""
    return {
        "active_downloads": (
            float(snapshot.downloads.active_count),
            {},
        ),
        "review_debt_total": (
            float(snapshot.review_debt.total),
            {
                "pending_matches": snapshot.review_debt.pending_matches,
                "suggestions": snapshot.review_debt.suggestions,
                "unmatched": snapshot.review_debt.unmatched_backlog,
            },
        ),
        "release_risk_count": (
            float(snapshot.release_risk.next_72h_count),
            {"next_7d": snapshot.release_risk.next_7d_count},
        ),
        "flow_through_rate": (
            float(snapshot.downloads.flow_through_rate or 0.0),
            {"terminal": snapshot.downloads.terminal_count},
        ),
        "client_reliability_rate": (
            float(snapshot.client_reliability.rate or 0.0),
            {"worst_client": snapshot.client_reliability.worst_client_label or ""},
        ),
        "storage_used_percent": (
            float(snapshot.storage.used_percent),
            {"used_bytes": snapshot.storage.used_bytes},
        ),
        "search_yield_rate": (
            float(snapshot.search_yield.rate or 0.0),
            {"searches": snapshot.search_yield.searches},
        ),
        "import_failure_count": (
            float(snapshot.import_failures.total),
            {"failed_jobs": snapshot.import_failures.failed_jobs},
        ),
        "unmatched_backlog": (
            float(snapshot.review_debt.unmatched_backlog),
            {},
        ),
        "health_problem_count": (
            float(snapshot.health.problem_count),
            {"unhealthy": snapshot.health.unhealthy_count},
        ),
    }
