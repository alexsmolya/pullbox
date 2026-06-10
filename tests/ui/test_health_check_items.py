"""Tests for health check item presenter mapping."""

from __future__ import annotations


def test_build_health_checks_from_details_maps_status_message_and_response() -> None:
    from pullbox.ui.health_check_items import build_health_checks_from_details

    checks = build_health_checks_from_details(
        {
            "checks": [
                {
                    "name": "Database",
                    "status": "healthy",
                    "message": "Connected in 42 ms",
                    "response_time_ms": 42.0,
                },
                {
                    "name": "Queue",
                    "status": "degraded",
                    "message": "Queue latency 120ms",
                },
            ]
        }
    )

    assert [check.key for check in checks] == ["check-0", "check-1"]
    assert [check.name for check in checks] == ["Database", "Queue"]
    assert [check.status_label for check in checks] == ["Healthy", "Degraded"]
    assert [check.response_label for check in checks] == ["42ms", "120ms"]
    assert checks[0].message == "Connected in 42ms"
    assert checks[1].pill_tone == "pill-warning"
