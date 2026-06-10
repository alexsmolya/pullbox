"""Tests for health detail footer item helpers."""

from __future__ import annotations

from pullbox.ui.health_presenters import (
    HealthComponentStatView,
    HealthComponentView,
)


def test_build_health_component_footer_items_keeps_component_status_and_known_stats() -> None:
    from pullbox.ui.health_footer_items import build_health_component_footer_items

    component = HealthComponentView(
        key="database",
        component_key="database",
        display_name="Database",
        detail_title="DATABASE DETAIL",
        status="degraded",
        status_label="Degraded",
        pill_tone="pill-warning",
        led_tone="led-warning",
        card_tone="health-card-warning",
        message="Slow",
        sublabel="2 checks",
        stats=(),
        detail_stats=(
            HealthComponentStatView(label="Response", value_label="15ms"),
            HealthComponentStatView(label="Last Check", value_label="2m ago"),
            HealthComponentStatView(label="Checks", value_label="2 (1 flagged)"),
            HealthComponentStatView(label="Ignored", value_label="Nope"),
        ),
        detail_variant="checks",
        checks=(),
        history=(),
        history_page=1,
        history_total_pages=1,
        history_total_count=0,
        history_sort="-checked_at",
        history_search_query="",
        history_base_path="/health/database",
    )

    assert build_health_component_footer_items(component) == (
        {"label": "component", "value": "Database", "led": None},
        {"label": "", "value": "Degraded", "led": "led-warning"},
        {"label": "response", "value": "15ms", "led": None},
        {"label": "last check", "value": "2m ago", "led": None},
        {"label": "checks", "value": "2 (1 flagged)", "led": None},
    )
