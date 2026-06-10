"""Tests for health component history loading."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pullbox.models.health import HealthCheckResult, HealthStatus


@pytest.mark.asyncio
async def test_load_health_component_histories_uses_detail_subchecks_and_summary_defaults(
    db_session,
) -> None:  # type: ignore[no-untyped-def]
    from pullbox.ui.health_component_history import load_health_component_histories

    now = datetime.now(UTC)
    db_session.add_all(
        [
            HealthCheckResult(
                component="database",
                check_name="summary",
                status=HealthStatus.HEALTHY,
                message="OK",
                response_time_ms=42.0,
                checked_at=now - timedelta(minutes=5),
                is_summary=True,
            ),
            HealthCheckResult(
                component="filesystem",
                check_name="summary",
                status=HealthStatus.UNHEALTHY,
                message="Summary failure",
                response_time_ms=900.0,
                checked_at=now - timedelta(minutes=3),
                is_summary=True,
            ),
            HealthCheckResult(
                component="filesystem",
                check_name="disk_space",
                status=HealthStatus.DEGRADED,
                message="Disk space is low",
                response_time_ms=125.0,
                checked_at=now - timedelta(minutes=1),
                is_summary=False,
            ),
            HealthCheckResult(
                component="filesystem",
                check_name="permissions",
                status=HealthStatus.HEALTHY,
                message="OK",
                response_time_ms=12.0,
                checked_at=now,
                is_summary=False,
            ),
        ]
    )
    await db_session.flush()

    result = await load_health_component_histories(
        db_session,
        component_keys=("database", "filesystem"),
        detail_component_key="filesystem",
        detail_history_page=1,
        detail_history_per_page=10,
        detail_history_sort="-checked_at",
        detail_history_search=" disk ",
        current_time=now,
        relative_time_label=lambda value, _reference: value.isoformat(),
    )

    assert [row.check_name for row in result.history_by_component["database"]] == ["Summary"]
    assert result.total_count_by_component["database"] == 1
    assert result.sort_by_component["database"] == "-checked_at"
    assert result.search_by_component["database"] == ""

    filesystem_rows = result.history_by_component["filesystem"]
    assert [row.check_name for row in filesystem_rows] == ["Disk Space"]
    assert filesystem_rows[0].status_label == "Degraded"
    assert result.page_by_component["filesystem"] == 1
    assert result.total_pages_by_component["filesystem"] == 1
    assert result.total_count_by_component["filesystem"] == 1
    assert result.sort_by_component["filesystem"] == "-checked_at"
    assert result.search_by_component["filesystem"] == "disk"
