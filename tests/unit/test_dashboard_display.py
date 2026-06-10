"""Tests for shared dashboard display helpers."""

from __future__ import annotations

from datetime import datetime, timedelta

from pullbox.ui.dashboard_display import (
    dashboard_completion_tone,
    dashboard_gauge_offset,
    dashboard_led_tone,
    dashboard_relative_time_label,
    dashboard_weekly_count_delta,
)


def test_dashboard_completion_tone_maps_thresholds() -> None:
    assert dashboard_completion_tone(80) == "success"
    assert dashboard_completion_tone(35) == "info"
    assert dashboard_completion_tone(34) == "warning"


def test_dashboard_led_tone_maps_known_states_and_defaults() -> None:
    assert dashboard_led_tone("critical") == "red"
    assert dashboard_led_tone("high") == "amber"
    assert dashboard_led_tone("watch") == "amber"
    assert dashboard_led_tone("healthy") == "green"
    assert dashboard_led_tone("info") == "blue"
    assert dashboard_led_tone("unknown") == "off"


def test_dashboard_gauge_offset_clamps_progress() -> None:
    assert dashboard_gauge_offset(1.0) == 0.0
    assert dashboard_gauge_offset(0.0) == 138.2
    assert dashboard_gauge_offset(2.0) == 0.0
    assert dashboard_gauge_offset(-1.0) == 138.2


def test_dashboard_relative_time_label_uses_compact_units() -> None:
    reference = datetime(2026, 6, 9, 12, 0, 0)

    assert dashboard_relative_time_label(reference - timedelta(seconds=10), reference) == "just now"
    assert dashboard_relative_time_label(reference - timedelta(minutes=12), reference) == "12m ago"
    assert dashboard_relative_time_label(reference - timedelta(hours=3), reference) == "3h ago"
    assert dashboard_relative_time_label(reference - timedelta(days=2), reference) == "2d ago"


def test_dashboard_weekly_count_delta_formats_first_run_and_stable_states() -> None:
    assert dashboard_weekly_count_delta(3, first_run=False) == "+3 this week"
    assert dashboard_weekly_count_delta(0, first_run=True) == "Collecting baseline"
    assert dashboard_weekly_count_delta(0, first_run=False) == "No changes this week"
