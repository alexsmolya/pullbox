"""Storage summary assembly for dashboard metrics."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pullbox.services.dashboard_helpers import (
    project_days_remaining,
    storage_growth_rates,
    storage_state_from_percent,
)
from pullbox.services.dashboard_types import StorageSummary

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pullbox.models.dashboard import DashboardStorageSnapshot


def build_dashboard_storage_summary(
    *,
    source_path: str,
    total_bytes: int,
    used_bytes: int,
    free_bytes: int,
    snapshots: Sequence[DashboardStorageSnapshot],
) -> StorageSummary:
    """Build a dashboard storage summary from current usage and snapshot history."""
    used_percent = (used_bytes / total_bytes) * 100 if total_bytes > 0 else 0.0
    state = storage_state_from_percent(used_percent)
    ordered_snapshots = list(snapshots)
    daily_growth_bytes, previous_daily_growth_bytes = storage_growth_rates(ordered_snapshots)
    runway_to_degraded_days = project_days_remaining(
        threshold_bytes=int(total_bytes * 0.80),
        used_bytes=used_bytes,
        daily_growth_bytes=daily_growth_bytes,
    )
    runway_to_unhealthy_days = project_days_remaining(
        threshold_bytes=int(total_bytes * 0.95),
        used_bytes=used_bytes,
        daily_growth_bytes=daily_growth_bytes,
    )

    return StorageSummary(
        source_path=source_path,
        total_bytes=int(total_bytes),
        used_bytes=int(used_bytes),
        free_bytes=int(free_bytes),
        used_percent=used_percent,
        state=state,
        runway_to_degraded_days=runway_to_degraded_days,
        runway_to_unhealthy_days=runway_to_unhealthy_days,
        daily_growth_bytes=daily_growth_bytes,
        previous_daily_growth_bytes=previous_daily_growth_bytes,
        snapshot_count=len(ordered_snapshots),
    )
