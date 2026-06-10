"""Dashboard intelligence value objects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date, datetime


@dataclass(frozen=True)
class DashboardPriority:
    """A ranked dashboard action item."""

    key: str
    title: str
    state: str
    state_label: str
    score: int
    why_it_matters: str
    evidence: str
    trend_label: str
    time_label: str
    cta_label: str
    cta_href: str


@dataclass(frozen=True)
class DashboardScorecard:
    """Top-level operational scorecard."""

    key: str
    title: str
    value_label: str
    delta_label: str
    state: str
    interpretation: str
    cta_label: str
    cta_href: str


@dataclass(frozen=True)
class DashboardWatchItem:
    """Short-horizon drift worth watching."""

    key: str
    title: str
    detail: str
    trend_label: str
    state: str
    cta_label: str
    cta_href: str


@dataclass(frozen=True)
class DashboardExceptionItem:
    """Aggregated anomaly cluster."""

    key: str
    title: str
    detail: str
    badge_label: str
    state: str
    cta_label: str
    cta_href: str


@dataclass(frozen=True)
class DashboardBriefing:
    """Top-level dashboard briefing."""

    state: str
    state_label: str
    headline: str
    summary: str
    priorities: tuple[DashboardPriority, ...]


@dataclass(frozen=True)
class DashboardLivePulse:
    """Compact pulse panel for the dashboard rail."""

    active_downloads: int
    pending_decisions: int
    next_72h_risk: int
    health_alerts: int


@dataclass(frozen=True)
class ActiveDownloadItem:
    """Lightweight active download row for the dashboard panel."""

    id: int
    title: str
    client_label: str
    progress_percent: float | None


@dataclass(frozen=True)
class DashboardIntelligence:
    """Full dashboard view model."""

    briefing: DashboardBriefing
    priorities: tuple[DashboardPriority, ...]
    scorecards: tuple[DashboardScorecard, ...]
    watch_items: tuple[DashboardWatchItem, ...]
    exceptions: tuple[DashboardExceptionItem, ...]
    freshness: datetime
    live_pulse: DashboardLivePulse
    is_first_run: bool


@dataclass(frozen=True)
class DownloadSummary:
    """Download funnel metrics for the dashboard."""

    active_count: int
    terminal_count: int
    imported_count: int
    previous_terminal_count: int
    previous_imported_count: int

    @property
    def flow_through_rate(self) -> float | None:
        if self.terminal_count <= 0:
            return None
        return (self.imported_count / self.terminal_count) * 100.0

    @property
    def previous_flow_through_rate(self) -> float | None:
        if self.previous_terminal_count <= 0:
            return None
        return (self.previous_imported_count / self.previous_terminal_count) * 100.0


@dataclass(frozen=True)
class ClientReliabilitySummary:
    """Client reliability summary for the current and previous windows."""

    rate: float | None
    previous_rate: float | None
    worst_client_label: str | None
    worst_client_rate: float | None
    worst_client_failures: int


@dataclass(frozen=True)
class ReviewDebtSummary:
    """Manual review backlog summary."""

    pending_matches: int
    suggestions: int
    unmatched_backlog: int
    total: int
    oldest_at: datetime | None
    reference_total: float | None


@dataclass(frozen=True)
class ReleaseRiskSummary:
    """Release coverage summary."""

    next_72h_count: int
    next_7d_count: int
    nearest_release_date: date | None
    reference_count: float | None


@dataclass(frozen=True)
class SearchYieldSummary:
    """Search yield comparison across two 7-day windows."""

    searches: int
    matched_results: int
    rate: float | None
    previous_searches: int
    previous_matched_results: int
    previous_rate: float | None


@dataclass(frozen=True)
class ImportFailureSummary:
    """Import failure trend data."""

    failed_jobs: int
    failed_files: int
    previous_failed_jobs: int
    previous_failed_files: int

    @property
    def total(self) -> int:
        return self.failed_jobs + self.failed_files

    @property
    def previous_total(self) -> int:
        return self.previous_failed_jobs + self.previous_failed_files


@dataclass(frozen=True)
class HealthSummary:
    """Current health status summary."""

    degraded_count: int
    unhealthy_count: int
    component_labels: tuple[str, ...]
    reference_problem_count: float | None

    @property
    def problem_count(self) -> int:
        return self.degraded_count + self.unhealthy_count


@dataclass(frozen=True)
class StorageSummary:
    """Disk usage and runway summary."""

    source_path: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    used_percent: float
    state: str
    runway_to_degraded_days: float | None
    runway_to_unhealthy_days: float | None
    daily_growth_bytes: float | None
    previous_daily_growth_bytes: float | None
    snapshot_count: int


@dataclass(frozen=True)
class FailureCluster:
    """Repeated anomaly cluster."""

    key: str
    title: str
    detail: str
    count: int
    cta_label: str
    cta_href: str
    state: str


@dataclass(frozen=True)
class DashboardSnapshot:
    """Internal snapshot used to derive dashboard view models."""

    computed_at: datetime
    latest_rollup_at: datetime | None
    downloads: DownloadSummary
    client_reliability: ClientReliabilitySummary
    review_debt: ReviewDebtSummary
    release_risk: ReleaseRiskSummary
    search_yield: SearchYieldSummary
    import_failures: ImportFailureSummary
    health: HealthSummary
    storage: StorageSummary
    failure_clusters: tuple[FailureCluster, ...]
    unmatched_clusters: tuple[FailureCluster, ...]
