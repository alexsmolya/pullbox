"""Dashboard intelligence scoring and formatting helpers."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from pullbox.models.health import HealthStatus

if TYPE_CHECKING:
    from pullbox.models.dashboard import DashboardStorageSnapshot
    from pullbox.services.dashboard_types import (
        ClientReliabilitySummary,
        ReleaseRiskSummary,
        ReviewDebtSummary,
        SearchYieldSummary,
        StorageSummary,
    )


def safe_percent(numerator: int, denominator: int) -> float | None:
    """Return a percentage, or None until the denominator has a usable baseline."""
    if denominator <= 0:
        return None
    return (numerator / denominator) * 100.0


def priority_score(
    severity: int,
    trend: int,
    aging: int,
    blast_radius: int,
    imminence: int,
) -> int:
    """Blend dashboard priority signals into a bounded score."""
    score = severity * 0.35 + trend * 0.20 + aging * 0.20 + blast_radius * 0.15 + imminence * 0.10
    return max(0, min(100, round(score)))


def priority_state(score: int) -> str:
    """Map a priority score to the dashboard state token."""
    if score >= 80:
        return "critical"
    if score >= 60:
        return "high"
    if score >= 40:
        return "watch"
    return "info"


def priority_state_label(score: int) -> str:
    """Map a priority score to a user-facing state label."""
    mapping = {
        "critical": "Critical",
        "high": "High",
        "watch": "Watch",
        "info": "Info",
    }
    return mapping[priority_state(score)]


def trend_score(current: int, reference: float | None) -> int:
    """Score growth from a reference count."""
    delta = delta_from_reference(current, reference)
    if delta is None or reference is None:
        return 20 if current > 0 else 0
    if reference <= 0:
        return 80 if current > 0 else 0
    growth = (delta / reference) * 100.0
    return max(0, min(100, round(growth)))


def rate_drop_score(current: float | None, previous: float | None) -> int:
    """Score a drop between two percentage-style rates."""
    if current is None or previous is None:
        return 0
    if current >= previous:
        return 0
    return max(0, min(100, round((previous - current) * 3)))


def rate_state_from_percent(value: float | None) -> str:
    """Map a reliability/rate percentage to a dashboard state."""
    if value is None:
        return "info"
    if value >= 90.0:
        return "healthy"
    if value >= 75.0:
        return "watch"
    return "critical"


def count_state(value: int, *, watch: int, critical: int) -> str:
    """Map a count to healthy/watch/critical thresholds."""
    if value >= critical:
        return "critical"
    if value >= watch:
        return "watch"
    return "healthy"


def format_percent_label(value: float | None) -> str:
    """Format a percentage while preserving the baseline-collection state."""
    if value is None:
        return "Collecting baseline"
    return f"{value:.0f}%"


def format_rate_delta(current: float | None, previous: float | None) -> str:
    """Format the delta between current and previous rates."""
    if current is None or previous is None:
        return "Collecting baseline"
    delta = current - previous
    if abs(delta) < 0.5:
        return "Flat vs last 7 days"
    direction = "up" if delta > 0 else "down"
    return f"{abs(delta):.0f} pts {direction} vs last 7 days"


def delta_from_reference(current: int, reference: float | None) -> int | None:
    """Return the rounded count delta from a rollup reference."""
    if reference is None:
        return None
    return current - round(reference)


def format_count_delta(current: int, reference: float | None) -> str:
    """Format a count delta from a rollup reference."""
    delta = delta_from_reference(current, reference)
    if delta is None:
        return "Collecting baseline"
    if delta == 0:
        return "Flat vs last week"
    direction = "up" if delta > 0 else "down"
    return f"{abs(delta)} {direction} vs last week"


def trend_label(current: int, reference: float | None, *, noun: str) -> str:
    """Format a count trend label with singular/plural noun handling."""
    delta = delta_from_reference(current, reference)
    if delta is None:
        return "Collecting baseline"
    if delta == 0:
        return "Flat vs last week"
    direction = "up" if delta > 0 else "down"
    suffix = noun if abs(delta) == 1 else f"{noun}s"
    return f"{abs(delta)} {suffix} {direction} vs last week"


def flow_through_interpretation(rate: float | None) -> str:
    """Interpret the download flow-through rate for the scorecard."""
    if rate is None:
        return "Waiting on enough history to call this."
    if rate >= 90.0:
        return "Most finished grabs are making it cleanly into the library."
    if rate >= 75.0:
        return "The pipeline is mostly keeping up, with a little cleanup still leaking through."
    return "Too many finished grabs are stalling before they land in the library."


def review_debt_interpretation(review_debt: ReviewDebtSummary) -> str:
    """Interpret the manual review backlog."""
    if review_debt.total <= 0:
        return "Nothing is piling up right now."
    if review_debt.oldest_at is None:
        return "There is cleanup waiting, but the age baseline is still thin."
    oldest_days = age_in_days(review_debt.oldest_at, datetime.now(UTC))
    if oldest_days <= 2:
        return "The queue is manageable if you clear it before the week stacks up."
    return "Some cleanup has been waiting long enough to slow the next pass down."


def release_risk_interpretation(release_risk: ReleaseRiskSummary) -> str:
    """Interpret near-term release coverage risk."""
    if release_risk.next_72h_count <= 0:
        return "Nothing in the next 72 hours looks exposed."
    if release_risk.nearest_release_date is None:
        return "A few releases are close enough to need a quick check."
    return (
        "The next uncovered release lands "
        f"{release_time_label(release_risk.nearest_release_date, date.today()).lower()}."
    )


def client_reliability_interpretation(summary: ClientReliabilitySummary) -> str:
    """Interpret download-client reliability."""
    if summary.rate is None:
        return "Waiting on enough finished downloads to judge reliability."
    if summary.worst_client_label is None:
        return "No client has enough history yet."
    if summary.rate >= 90.0:
        return f"{summary.worst_client_label} is the slowest lane, but nothing looks alarming."
    return f"{summary.worst_client_label} is dragging the average down."


def storage_runway_label(storage: StorageSummary) -> str:
    """Format storage runway for user-facing dashboard copy."""
    if storage.runway_to_degraded_days is None:
        return "Collecting baseline"
    if storage.state == "unhealthy":
        return "Past the unhealthy threshold"
    if storage.runway_to_degraded_days <= 0:
        return "At the degraded threshold"
    return f"{storage.runway_to_degraded_days:.0f} days to the degraded threshold"


def storage_growth_label(storage: StorageSummary) -> str:
    """Format the current storage growth baseline."""
    if storage.daily_growth_bytes is None:
        return "Collecting baseline"
    per_day_gb = storage.daily_growth_bytes / (1024 * 1024 * 1024)
    return f"{per_day_gb:.2f} GB/day on the current baseline"


def storage_interpretation(storage: StorageSummary) -> str:
    """Interpret disk usage and projected runway."""
    if storage.state == "unhealthy":
        return "Storage is already past the safe line."
    if storage.runway_to_degraded_days is None:
        return "Waiting on enough snapshots to project runway."
    if storage.runway_to_degraded_days > 60:
        return "You still have room, but the growth line is worth keeping around."
    if storage.runway_to_degraded_days > 14:
        return "The runway is shrinking enough to keep an eye on."
    return "This is close enough to become a real interruption."


def storage_state_from_percent(used_percent: float) -> str:
    """Map disk usage percentage to a health-state token."""
    if used_percent > 95.0:
        return HealthStatus.UNHEALTHY.value
    if used_percent > 80.0:
        return HealthStatus.DEGRADED.value
    return HealthStatus.HEALTHY.value


def storage_growth_rates(
    snapshots: list[DashboardStorageSnapshot],
) -> tuple[float | None, float | None]:
    """Return current and previous daily storage growth rates."""
    if len(snapshots) < 2:
        return None, None

    first = snapshots[0]
    last = snapshots[-1]
    day_span = max(1, (last.snapshot_date - first.snapshot_date).days)
    current_rate = (last.used_bytes - first.used_bytes) / day_span

    if len(snapshots) < 4:
        return current_rate, None

    previous_last = snapshots[-2]
    previous_first = snapshots[0]
    previous_span = max(1, (previous_last.snapshot_date - previous_first.snapshot_date).days)
    previous_rate = (previous_last.used_bytes - previous_first.used_bytes) / previous_span
    return current_rate, previous_rate


def project_days_remaining(
    *,
    threshold_bytes: int,
    used_bytes: int,
    daily_growth_bytes: float | None,
) -> float | None:
    """Project days until a storage threshold is reached."""
    if daily_growth_bytes is None or daily_growth_bytes <= 0:
        return None
    remaining = threshold_bytes - used_bytes
    if remaining <= 0:
        return 0.0
    return remaining / daily_growth_bytes


def storage_is_accelerating(storage: StorageSummary) -> bool:
    """Return whether storage growth is accelerating against the prior baseline."""
    if storage.daily_growth_bytes is None or storage.previous_daily_growth_bytes is None:
        return False
    if storage.previous_daily_growth_bytes <= 0:
        return storage.daily_growth_bytes > 0
    return storage.daily_growth_bytes > storage.previous_daily_growth_bytes * 1.25


def storage_trend_score(storage: StorageSummary) -> int:
    """Score storage growth acceleration."""
    if storage.daily_growth_bytes is None:
        return 10
    if storage.previous_daily_growth_bytes is None or storage.previous_daily_growth_bytes <= 0:
        return 30 if storage.daily_growth_bytes > 0 else 0
    growth_ratio = storage.daily_growth_bytes / storage.previous_daily_growth_bytes
    return max(0, min(100, round((growth_ratio - 1.0) * 100)))


def count_label(count: int, *, singular: str) -> str:
    """Format a count with singular/plural noun handling."""
    suffix = singular if count == 1 else f"{singular}s"
    return f"{count} {suffix}"


def storage_severity(storage: StorageSummary) -> int:
    """Score storage severity from state and runway."""
    if storage.state == "unhealthy":
        return 100
    if storage.state == "degraded":
        return 80
    if storage.runway_to_degraded_days is None:
        return 0
    if storage.runway_to_degraded_days <= 7:
        return 85
    if storage.runway_to_degraded_days <= 21:
        return 65
    if storage.runway_to_degraded_days <= 45:
        return 45
    return 0


def storage_imminence(storage: StorageSummary) -> int:
    """Score storage urgency from projected runway."""
    if storage.runway_to_degraded_days is None:
        return 20
    if storage.runway_to_degraded_days <= 7:
        return 95
    if storage.runway_to_degraded_days <= 21:
        return 70
    if storage.runway_to_degraded_days <= 45:
        return 45
    return 20


def search_yield_is_drifting(summary: SearchYieldSummary) -> bool:
    """Return whether search yield fell enough to surface as dashboard drift."""
    if summary.rate is None or summary.previous_rate is None:
        return False
    if summary.searches < 3 or summary.previous_searches < 3:
        return False
    return summary.rate <= summary.previous_rate - 10.0


def age_in_days(older: datetime | None, newer: datetime) -> int:
    """Return the whole-day age between two datetimes."""
    if older is None:
        return 0
    delta = newer - older
    return max(0, int(delta.total_seconds() // 86400))


def oldest_age_label(older: datetime | None, newer: datetime) -> str:
    """Format the age of the oldest queue item."""
    if older is None:
        return "Fresh queue"
    days = age_in_days(older, newer)
    if days <= 0:
        return "Opened today"
    if days == 1:
        return "Oldest item is 1 day old"
    return f"Oldest item is {days} days old"


def days_until(target: date | None, today: date) -> int:
    """Return days until a date, using a large sentinel for missing dates."""
    if target is None:
        return 999
    return max(0, (target - today).days)


def release_time_label(target: date | None, today: date) -> str:
    """Format the time until a release date."""
    if target is None:
        return "Soon"
    days = days_until(target, today)
    if days <= 0:
        return "Due today"
    if days == 1:
        return "Due tomorrow"
    return f"Due in {days} days"
