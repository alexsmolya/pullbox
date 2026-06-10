"""Tests for shared health subject history loading."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pullbox.models.health import HealthCheckResult, HealthStatus


@pytest.mark.asyncio
async def test_load_health_subject_history_uses_subchecks_and_summary_health(
    db_session,
) -> None:  # type: ignore[no-untyped-def]
    from pullbox.ui.health_subject_history import load_health_subject_history

    now = datetime.now(UTC)
    subject_key = "7"
    db_session.add_all(
        [
            HealthCheckResult(
                component="indexers",
                subject_key=subject_key,
                check_name="summary",
                status=HealthStatus.UNHEALTHY,
                message="Timeout",
                details_json=None,
                response_time_ms=9000.0,
                checked_at=now,
                is_summary=True,
            ),
            HealthCheckResult(
                component="indexers",
                subject_key=subject_key,
                check_name="summary",
                status=HealthStatus.DEGRADED,
                message="Slow",
                details_json=None,
                response_time_ms=1200.0,
                checked_at=now - timedelta(minutes=1),
                is_summary=True,
            ),
            HealthCheckResult(
                component="indexers",
                subject_key=subject_key,
                check_name="summary",
                status=HealthStatus.HEALTHY,
                message="OK",
                details_json=None,
                response_time_ms=100.0,
                checked_at=now - timedelta(minutes=2),
                is_summary=True,
            ),
            HealthCheckResult(
                component="indexers",
                subject_key=subject_key,
                check_name="summary",
                status=HealthStatus.UNHEALTHY,
                message="Older failure",
                details_json=None,
                response_time_ms=9000.0,
                checked_at=now - timedelta(minutes=3),
                is_summary=True,
            ),
            HealthCheckResult(
                component="indexers",
                subject_key=subject_key,
                check_name="latency_probe",
                status=HealthStatus.DEGRADED,
                message="Latency is high",
                details_json=None,
                response_time_ms=1200.0,
                checked_at=now,
                is_summary=False,
            ),
            HealthCheckResult(
                component="indexers",
                subject_key=subject_key,
                check_name="auth",
                status=HealthStatus.HEALTHY,
                message="OK",
                details_json=None,
                response_time_ms=50.0,
                checked_at=now - timedelta(seconds=30),
                is_summary=False,
            ),
            HealthCheckResult(
                component="indexers",
                subject_key="other",
                check_name="latency_probe",
                status=HealthStatus.UNHEALTHY,
                message="Latency is high",
                details_json=None,
                response_time_ms=9000.0,
                checked_at=now,
                is_summary=False,
            ),
        ]
    )
    await db_session.flush()

    result = await load_health_subject_history(
        db_session,
        component_key="indexers",
        subject_key=subject_key,
        page=1,
        sort="-checked_at",
        search=" latency ",
    )

    assert result.normalized_search == "latency"
    assert result.normalized_sort == "-checked_at"
    assert result.page == 1
    assert result.total_pages == 1
    assert result.total_count == 1
    assert [row.check_name for row in result.rows] == ["latency_probe"]
    assert result.latest_healthy_at == now - timedelta(minutes=2)
    assert result.consecutive_failures == 2
