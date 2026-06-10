"""Tests for shared health history row presenter mapping."""

from __future__ import annotations

from datetime import UTC, datetime

from pullbox.models.health import HealthCheckResult, HealthStatus


def test_build_health_history_rows_maps_common_display_fields() -> None:
    from pullbox.ui.health_history_rows import build_health_history_rows

    checked_at = datetime(2026, 6, 6, 12, 0, tzinfo=UTC)
    current_time = datetime(2026, 6, 6, 12, 5, tzinfo=UTC)
    row = HealthCheckResult(
        component="download_clients",
        check_name="queue_access",
        status=HealthStatus.UNHEALTHY,
        response_time_ms=175.4,
        checked_at=checked_at,
    )
    row.id = 42

    result = build_health_history_rows(
        (row,),
        key_prefix="download-client",
        current_time=current_time,
        relative_time_label=lambda value, reference: (
            f"{int((reference - value).total_seconds() // 60)}m ago"
        ),
    )

    assert len(result) == 1
    view = result[0]
    assert view.key == "download-client-42"
    assert view.time_label == "5m ago"
    assert view.check_name == "Queue Access"
    assert view.status_label == "Unhealthy"
    assert view.pill_tone == "pill-error"
    assert view.response_label == "175ms"
