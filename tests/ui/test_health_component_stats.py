"""Tests for health component stat presenter helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pullbox.ui.health_presenters import HealthCheckItemView


def _check(name: str, status: str, message: str = "OK") -> HealthCheckItemView:
    return HealthCheckItemView(
        key=name,
        name=name,
        status=status,
        status_label=status.capitalize(),
        pill_tone="",
        led_tone="",
        message=message,
        response_label="",
    )


def test_health_attention_label_prioritizes_unhealthy_then_degraded() -> None:
    from pullbox.ui.health_component_stats import health_attention_label

    assert health_attention_label((_check("one", "healthy"),), down_noun="down") == "All clear"
    assert (
        health_attention_label(
            (_check("one", "degraded"), _check("two", "healthy")),
            down_noun="down",
        )
        == "1 need review"
    )
    assert (
        health_attention_label(
            (_check("one", "unhealthy"), _check("two", "degraded")),
            down_noun="offline",
        )
        == "1 offline"
    )


def test_health_component_sublabel_counts_indexer_proxy_and_indexers() -> None:
    from pullbox.ui.health_component_stats import health_component_sublabel

    details = {
        "checks": [
            {"subject_kind": "proxy", "subject_key": "prowlarr"},
            {"subject_kind": "indexer", "subject_key": "1"},
            {"subject_kind": "indexer", "subject_key": "2"},
        ]
    }

    assert health_component_sublabel("indexers", (), details) == "1 proxy + 2 indexers"
    assert (
        health_component_sublabel("filesystem", (_check("disk", "healthy"),), {})
        == "1 paths checked"
    )
    assert (
        health_component_sublabel("system", (_check("cpu", "healthy"),), {}) == "1 resource checks"
    )


def test_health_component_card_stats_keep_specialized_indexer_summary() -> None:
    from pullbox.ui.health_component_stats import health_component_card_stats

    current_time = datetime(2026, 6, 6, 12, 5, tzinfo=UTC)
    details = {
        "checks": [
            {
                "subject_kind": "proxy",
                "subject_key": "prowlarr",
                "status": "degraded",
                "response_time_ms": 250.0,
            },
            {"subject_kind": "indexer", "subject_key": "1", "status": "healthy"},
            {"subject_kind": "indexer", "subject_key": "2", "status": "unhealthy"},
        ]
    }

    stats = health_component_card_stats(
        "indexers",
        checks=(_check("one", "healthy"), _check("two", "unhealthy")),
        response_ms=99.0,
        last_checked=current_time - timedelta(minutes=1),
        current_time=current_time,
        details=details,
        message="Indexers need attention",
        relative_time_label=lambda value, reference: (
            f"{int((reference - value).total_seconds() // 60)}m ago"
        ),
    )

    assert [(stat.label, stat.value_label, stat.tone) for stat in stats] == [
        ("Prowlarr", "250ms", "warning"),
        ("Indexers", "1/2 OK", "default"),
    ]


def test_health_component_detail_stats_flags_attention_count() -> None:
    from pullbox.ui.health_component_stats import health_component_detail_stats

    current_time = datetime(2026, 6, 6, 12, 5, tzinfo=UTC)
    stats = health_component_detail_stats(
        "database",
        checks=(_check("db", "degraded"), _check("pool", "healthy")),
        response_ms=15.0,
        last_checked=current_time - timedelta(minutes=2),
        current_time=current_time,
        details={},
        message="SQLite slow",
        relative_time_label=lambda value, reference: (
            f"{int((reference - value).total_seconds() // 60)}m ago"
        ),
    )

    assert [(stat.label, stat.value_label, stat.tone) for stat in stats] == [
        ("Status", "SQLite slow", "default"),
        ("Response", "15ms", "default"),
        ("Last Check", "2m ago", "default"),
        ("Checks", "2 (1 flagged)", "danger"),
    ]
