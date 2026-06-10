"""Shared dashboard display formatting helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime


def dashboard_completion_tone(value: int) -> str:
    """Choose the gauge tone for completion metrics."""
    if value >= 80:
        return "success"
    if value >= 35:
        return "info"
    return "warning"


def dashboard_led_tone(state: str) -> str:
    """Map dashboard states to led dot tones."""
    mapping = {
        "critical": "red",
        "high": "amber",
        "watch": "amber",
        "healthy": "green",
        "info": "blue",
    }
    return mapping.get(state, "off")


def dashboard_gauge_offset(progress: float) -> float:
    """Return the SVG stroke offset for a mission-control gauge."""
    circumference = 138.2
    clamped = max(0.0, min(progress, 1.0))
    return round(circumference * (1.0 - clamped), 1)


def dashboard_relative_time_label(value: datetime, reference: datetime) -> str:
    """Return a compact relative label like `12m ago`."""
    delta_seconds = int((reference - value).total_seconds())
    if delta_seconds <= 15:
        return "just now"
    if delta_seconds < 3600:
        return f"{max(1, round(delta_seconds / 60))}m ago"
    if delta_seconds < 86400:
        return f"{max(1, round(delta_seconds / 3600))}h ago"
    return f"{max(1, round(delta_seconds / 86400))}d ago"


def dashboard_weekly_count_delta(count: int, first_run: bool) -> str:
    """Format a simple weekly delta label for scoreboard counts."""
    if count > 0:
        return f"+{count} this week"
    if first_run:
        return "Collecting baseline"
    return "No changes this week"
