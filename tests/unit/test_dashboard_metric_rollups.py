from __future__ import annotations

from datetime import date, datetime

from pullbox.models.download import DownloadClientType
from pullbox.services.dashboard_metric_rollups import (
    DASHBOARD_ROLLUP_KEYS,
    dashboard_download_client_label,
    dashboard_hour_bucket_start,
    dashboard_rollup_payload,
)
from pullbox.services.dashboard_types import (
    ClientReliabilitySummary,
    DashboardSnapshot,
    DownloadSummary,
    HealthSummary,
    ImportFailureSummary,
    ReleaseRiskSummary,
    ReviewDebtSummary,
    SearchYieldSummary,
    StorageSummary,
)


def _dashboard_snapshot() -> DashboardSnapshot:
    return DashboardSnapshot(
        computed_at=datetime(2026, 6, 9, 12, 34, 56),
        latest_rollup_at=None,
        downloads=DownloadSummary(
            active_count=3,
            terminal_count=8,
            imported_count=6,
            previous_terminal_count=4,
            previous_imported_count=2,
        ),
        client_reliability=ClientReliabilitySummary(
            rate=82.5,
            previous_rate=70.0,
            worst_client_label="Transmission",
            worst_client_rate=60.0,
            worst_client_failures=2,
        ),
        review_debt=ReviewDebtSummary(
            pending_matches=2,
            suggestions=1,
            unmatched_backlog=4,
            total=7,
            oldest_at=None,
            reference_total=5.0,
        ),
        release_risk=ReleaseRiskSummary(
            next_72h_count=9,
            next_7d_count=14,
            nearest_release_date=date(2026, 6, 10),
            reference_count=3.0,
        ),
        search_yield=SearchYieldSummary(
            searches=11,
            matched_results=5,
            rate=45.5,
            previous_searches=8,
            previous_matched_results=3,
            previous_rate=37.5,
        ),
        import_failures=ImportFailureSummary(
            failed_jobs=1,
            failed_files=2,
            previous_failed_jobs=0,
            previous_failed_files=1,
        ),
        health=HealthSummary(
            degraded_count=1,
            unhealthy_count=2,
            component_labels=("Indexer degraded", "Storage failing"),
            reference_problem_count=1.0,
        ),
        storage=StorageSummary(
            source_path="/comics",
            total_bytes=1000,
            used_bytes=650,
            free_bytes=350,
            used_percent=65.0,
            state="healthy",
            runway_to_degraded_days=None,
            runway_to_unhealthy_days=None,
            daily_growth_bytes=None,
            previous_daily_growth_bytes=None,
            snapshot_count=1,
        ),
        failure_clusters=(),
        unmatched_clusters=(),
    )


def test_dashboard_download_client_label_formats_known_and_unknown_clients() -> None:
    assert dashboard_download_client_label(DownloadClientType.SABNZBD) == "SABnzbd"
    assert dashboard_download_client_label(DownloadClientType.NZBGET) == "NZBGet"
    assert dashboard_download_client_label("custom_client") == "Custom Client"


def test_dashboard_hour_bucket_start_truncates_to_the_hour() -> None:
    assert dashboard_hour_bucket_start(datetime(2026, 6, 9, 12, 34, 56, 123)) == datetime(
        2026,
        6,
        9,
        12,
    )


def test_dashboard_rollup_payload_matches_expected_metric_contract() -> None:
    payload = dashboard_rollup_payload(_dashboard_snapshot())

    assert tuple(payload) == DASHBOARD_ROLLUP_KEYS
    assert payload["active_downloads"] == (3.0, {})
    assert payload["review_debt_total"] == (
        7.0,
        {"pending_matches": 2, "suggestions": 1, "unmatched": 4},
    )
    assert payload["release_risk_count"] == (9.0, {"next_7d": 14})
    assert payload["flow_through_rate"] == (75.0, {"terminal": 8})
    assert payload["client_reliability_rate"] == (82.5, {"worst_client": "Transmission"})
    assert payload["storage_used_percent"] == (65.0, {"used_bytes": 650})
    assert payload["search_yield_rate"] == (45.5, {"searches": 11})
    assert payload["import_failure_count"] == (3.0, {"failed_jobs": 1})
    assert payload["unmatched_backlog"] == (4.0, {})
    assert payload["health_problem_count"] == (3.0, {"unhealthy": 2})
