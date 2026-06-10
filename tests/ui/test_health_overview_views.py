"""Tests for health overview presenter assembly."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_build_health_view_orders_components_and_computes_overview_counts(
    db_session,
) -> None:  # type: ignore[no-untyped-def]
    from pullbox.ui.health_overview_views import build_health_view

    current_time = datetime(2026, 6, 7, 12, 0, tzinfo=UTC)
    health_view = await build_health_view(
        db_session,
        components=[
            {
                "component": "database",
                "status": "healthy",
                "message": "Database responded in 42 ms",
                "response_time_ms": 42.0,
                "last_checked": current_time,
                "details": {
                    "checks": [
                        {
                            "name": "SQLite",
                            "status": "healthy",
                            "message": "OK 42 ms",
                            "response_time_ms": 42.0,
                        }
                    ]
                },
            },
            {
                "component": "filesystem",
                "status": "unhealthy",
                "message": "Disk full",
                "response_time_ms": None,
                "last_checked": current_time,
                "details": {"checks": []},
            },
        ],
        overall_status="unhealthy",
        search_stats=SimpleNamespace(
            total_searches=4,
            total_matched=3,
            total_rejected=1,
            total_results_parsed=12,
            last_search_at=None,
        ),
        gauge_offset=lambda value: round(value, 2),
        relative_time_label=lambda value, reference: (
            f"{int((reference - value).total_seconds() // 60)}m ago"
        ),
        current_time=current_time,
    )

    assert health_view.overall_status == "unhealthy"
    assert health_view.total_monitors == 7
    assert health_view.total_checks == 7
    assert [component.key for component in health_view.components] == [
        "database",
        "filesystem",
        "comicvine",
        "download_clients",
        "indexers",
        "scheduler",
        "system",
    ]
    assert health_view.components[0].message == "Database responded in 42ms"
    assert health_view.components[0].checks[0].response_label == "42ms"
    assert health_view.components[2].status == "unknown"
    assert [
        (gauge.key, gauge.value_label, gauge.stroke_offset) for gauge in health_view.gauges
    ] == [
        ("healthy", "1", 0.14),
        ("degraded", "0", 0),
        ("unhealthy", "1", 0.14),
    ]
    assert [(item.key, item.value_label, item.delta_label) for item in health_view.scoreboard] == [
        ("searches", "4", "Recorded"),
        ("matched", "3", "75% match rate"),
        ("rejected", "1", "25% rejection"),
        ("parsed", "12", "Observed"),
        ("last-search", "—", "Search activity"),
    ]
