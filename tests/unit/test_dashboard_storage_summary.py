from __future__ import annotations

from datetime import date

from pullbox.models.dashboard import DashboardStorageSnapshot
from pullbox.models.health import HealthStatus
from pullbox.services.dashboard_storage_summary import build_dashboard_storage_summary


def test_build_dashboard_storage_summary_handles_zero_total_bytes() -> None:
    summary = build_dashboard_storage_summary(
        source_path="/comics",
        total_bytes=0,
        used_bytes=10,
        free_bytes=0,
        snapshots=[],
    )

    assert summary.source_path == "/comics"
    assert summary.used_percent == 0.0
    assert summary.state == HealthStatus.HEALTHY.value
    assert summary.runway_to_degraded_days is None
    assert summary.runway_to_unhealthy_days is None
    assert summary.snapshot_count == 0


def test_build_dashboard_storage_summary_projects_growth_runway() -> None:
    snapshots = [
        DashboardStorageSnapshot(
            snapshot_date=date(2026, 6, 1),
            source_path="/comics",
            total_bytes=1000,
            used_bytes=500,
            free_bytes=500,
            used_percent=50.0,
        ),
        DashboardStorageSnapshot(
            snapshot_date=date(2026, 6, 3),
            source_path="/comics",
            total_bytes=1000,
            used_bytes=600,
            free_bytes=400,
            used_percent=60.0,
        ),
    ]

    summary = build_dashboard_storage_summary(
        source_path="/comics",
        total_bytes=1000,
        used_bytes=600,
        free_bytes=400,
        snapshots=snapshots,
    )

    assert summary.used_percent == 60.0
    assert summary.state == HealthStatus.HEALTHY.value
    assert summary.daily_growth_bytes == 50.0
    assert summary.previous_daily_growth_bytes is None
    assert summary.runway_to_degraded_days == 4.0
    assert summary.runway_to_unhealthy_days == 7.0
    assert summary.snapshot_count == 2


def test_build_dashboard_storage_summary_uses_dashboard_thresholds() -> None:
    degraded = build_dashboard_storage_summary(
        source_path="/comics",
        total_bytes=1000,
        used_bytes=810,
        free_bytes=190,
        snapshots=[],
    )
    unhealthy = build_dashboard_storage_summary(
        source_path="/comics",
        total_bytes=1000,
        used_bytes=960,
        free_bytes=40,
        snapshots=[],
    )

    assert degraded.state == HealthStatus.DEGRADED.value
    assert unhealthy.state == HealthStatus.UNHEALTHY.value
