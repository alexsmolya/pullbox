"""Health UI presenter models and pure formatting helpers."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from pullbox.core.duration_format import format_duration_ms_label


def _object_to_int(value: object) -> int:
    """Best-effort integer coercion for template-facing sort values."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


@dataclass(frozen=True)
class HealthGaugeView:
    """Summary gauge for the health mission-control header."""

    key: str
    label: str
    value_label: str
    tone: str
    stroke_offset: float


@dataclass(frozen=True)
class HealthScoreboardItemView:
    """Scoreboard metric for search telemetry."""

    key: str
    label: str
    value_label: str
    delta_label: str


@dataclass(frozen=True)
class HealthComponentStatView:
    """Compact stat tile used on cards and detail panels."""

    label: str
    value_label: str
    tone: str = "default"


@dataclass(frozen=True)
class HealthCheckItemView:
    """Rendered health check row."""

    key: str
    name: str
    status: str
    status_label: str
    pill_tone: str
    led_tone: str
    message: str
    response_label: str


@dataclass(frozen=True)
class HealthHistoryRowView:
    """Recent history row for a single health component."""

    key: str
    time_label: str
    check_name: str
    status_label: str
    pill_tone: str
    response_label: str


@dataclass(frozen=True)
class HealthSubjectSummaryView:
    """Summary row for a multi-entity health component."""

    key: str
    display_name: str
    kind_label: str
    detail_label: str
    response_label: str
    last_check_label: str
    status_label: str
    pill_tone: str
    led_tone: str
    href: str


@dataclass(frozen=True)
class HealthComponentView:
    """Card + detail state for one monitored component."""

    key: str
    component_key: str
    display_name: str
    detail_title: str
    status: str
    status_label: str
    pill_tone: str
    led_tone: str
    card_tone: str
    message: str
    sublabel: str
    stats: tuple[HealthComponentStatView, ...]
    detail_stats: tuple[HealthComponentStatView, ...]
    detail_variant: str
    checks: tuple[HealthCheckItemView, ...]
    history: tuple[HealthHistoryRowView, ...]
    history_page: int = 1
    history_total_pages: int = 1
    history_total_count: int = 0
    history_sort: str = "-checked_at"
    history_search_query: str = ""
    subject_key: str | None = None
    history_base_path: str = ""
    back_href: str = "/health"
    back_label: str = "Back to health"


@dataclass(frozen=True)
class HealthFooterStripView:
    """Footer strip summary for the health page."""

    total_monitors: int
    total_checks: int
    healthy_count: int
    degraded_count: int
    unhealthy_count: int


@dataclass(frozen=True)
class HealthMonitoringView:
    """Aggregated health presenter for the mission-control layout."""

    overall_status: str
    total_monitors: int
    total_checks: int
    gauges: tuple[HealthGaugeView, ...]
    scoreboard: tuple[HealthScoreboardItemView, ...]
    components: tuple[HealthComponentView, ...]
    footer: HealthFooterStripView


def _health_pill_tone(status: str) -> str:
    """Map health state to the shared pill contract."""
    mapping = {
        "healthy": "pill-success",
        "degraded": "pill-warning",
        "unhealthy": "pill-error",
        "unknown": "pill-neutral",
    }
    return mapping.get(status, "pill-neutral")


def _health_led_tone(status: str) -> str:
    """Map health state to the LED dot tone."""
    mapping = {
        "healthy": "green",
        "degraded": "amber",
        "unhealthy": "red",
        "unknown": "off",
    }
    return mapping.get(status, "off")


def _health_card_tone(status: str) -> str:
    """Map health state to card accent tone."""
    mapping = {
        "healthy": "success",
        "degraded": "warning",
        "unhealthy": "danger",
        "unknown": "neutral",
    }
    return mapping.get(status, "neutral")


def _health_response_label(response_ms: object) -> str:
    """Format health response timing."""
    return format_duration_ms_label(response_ms)


def _health_check_response_label(message: str) -> str:
    """Extract a compact response label from a check message when possible."""
    match = re.search(r"(\d+(?:\.\d+)?)\s*ms\b", message)
    if match:
        return format_duration_ms_label(float(match.group(1)))
    return message


def _health_parenthetical_next_line(value: str) -> str:
    """Move the first parenthetical segment onto its own line for compact cards."""
    if " (" not in value:
        return value
    return value.replace(" (", "\n(", 1)


def _mapping_text(details: object, key: str) -> str:
    """Safely read a string-ish value from a details mapping."""
    if not isinstance(details, Mapping):
        return ""
    value = details.get(key)
    if value is None:
        return ""
    return str(value)
