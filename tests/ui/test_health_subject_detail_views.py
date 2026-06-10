"""Tests for health subject detail presenter builders."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pullbox.models.client import DownloadClientConfig
from pullbox.models.config import SystemConfig
from pullbox.models.download import DownloadClientType
from pullbox.models.health import HealthCheckResult, HealthCurrentStatus, HealthStatus


def _relative_time(value: datetime, reference: datetime) -> str:
    return f"{int((reference - value).total_seconds() // 60)}m ago"


@pytest.mark.asyncio
async def test_build_download_client_detail_view_uses_config_current_status_and_history(
    db_session,
) -> None:  # type: ignore[no-untyped-def]
    from pullbox.ui.health_subject_detail_views import build_download_client_detail_view

    current_time = datetime(2026, 6, 7, 12, 0, tzinfo=UTC)
    client = DownloadClientConfig(
        name="SAB Main",
        client_type=DownloadClientType.SABNZBD,
        url="https://sab.example:9090/api",
        enabled=True,
    )
    db_session.add(client)
    await db_session.flush()
    subject_key = str(client.id)
    db_session.add_all(
        [
            HealthCurrentStatus(
                component="download_clients",
                current_key="summary",
                check_name="summary",
                subject_key=subject_key,
                subject_key_norm=subject_key,
                status=HealthStatus.DEGRADED,
                message="Client slow 150 ms",
                details_json=(
                    '{"version":"4.0.0","checks":[{"name":"Queue access",'
                    '"status":"degraded","message":"Queue 150 ms",'
                    '"response_time_ms":150.0}]}'
                ),
                response_time_ms=150.0,
                checked_at=current_time - timedelta(minutes=1),
                is_summary=True,
            ),
            HealthCheckResult(
                component="download_clients",
                check_name="summary",
                subject_key=subject_key,
                status=HealthStatus.DEGRADED,
                message="Client slow",
                response_time_ms=150.0,
                checked_at=current_time - timedelta(minutes=1),
                is_summary=True,
            ),
            HealthCheckResult(
                component="download_clients",
                check_name="summary",
                subject_key=subject_key,
                status=HealthStatus.HEALTHY,
                message="Healthy",
                response_time_ms=20.0,
                checked_at=current_time - timedelta(minutes=10),
                is_summary=True,
            ),
        ]
    )
    await db_session.flush()

    view = await build_download_client_detail_view(
        db_session,
        subject_key=subject_key,
        current_time=current_time,
        history_page=1,
        history_sort="-checked_at",
        history_search="",
        relative_time_label=_relative_time,
        download_client_type_label=lambda value: value.upper(),
    )

    assert view.display_name == "SAB Main"
    assert view.status == "degraded"
    assert view.message == "Client slow 150ms"
    assert view.sublabel == "SABNZBD"
    assert [check.name for check in view.checks] == ["Queue access"]
    assert view.checks[0].message == "Queue 150ms"
    assert [(stat.label, stat.value_label) for stat in view.detail_stats] == [
        ("Status", "Client slow 150ms"),
        ("Response", "150ms"),
        ("Last Healthy", "10m ago"),
        ("Consecutive Fails", "1"),
        ("Host", "sab.example"),
        ("Port", "9090"),
        ("Protocol", "HTTPS · 4.0.0"),
    ]
    assert [row.check_name for row in view.history] == ["Summary", "Summary"]
    assert view.history_base_path == f"/health/download_clients/{subject_key}"


@pytest.mark.asyncio
async def test_build_indexer_detail_view_builds_prowlarr_proxy_detail(
    db_session,
) -> None:  # type: ignore[no-untyped-def]
    from pullbox.ui.health_subject_detail_views import build_indexer_detail_view

    current_time = datetime(2026, 6, 7, 12, 0, tzinfo=UTC)
    db_session.add_all(
        [
            SystemConfig(key="prowlarr_url", value="http://prowlarr.example:9696"),
            SystemConfig(key="prowlarr_api_key", value="secret"),
            HealthCurrentStatus(
                component="indexers",
                current_key="summary",
                check_name="summary",
                subject_key="prowlarr",
                subject_key_norm="prowlarr",
                status=HealthStatus.HEALTHY,
                message="Prowlarr OK",
                details_json='{"indexer_count":3,"checks":[]}',
                response_time_ms=88.0,
                checked_at=current_time - timedelta(minutes=2),
                is_summary=True,
            ),
            HealthCheckResult(
                component="indexers",
                check_name="summary",
                subject_key="prowlarr",
                status=HealthStatus.HEALTHY,
                message="Prowlarr OK",
                response_time_ms=88.0,
                checked_at=current_time - timedelta(minutes=2),
                is_summary=True,
            ),
        ]
    )
    await db_session.flush()

    view = await build_indexer_detail_view(
        db_session,
        subject_key="prowlarr",
        current_time=current_time,
        history_page=1,
        history_sort="-checked_at",
        history_search="",
        relative_time_label=_relative_time,
    )

    assert view.display_name == "Prowlarr"
    assert view.sublabel == "Search proxy"
    assert view.status == "healthy"
    assert [(stat.label, stat.value_label) for stat in view.detail_stats] == [
        ("Status", "Prowlarr OK"),
        ("Response", "88ms"),
        ("Last Healthy", "2m ago"),
        ("Consecutive Fails", "0"),
        ("Host", "prowlarr.example"),
        ("Port", "9696"),
        ("Indexers", "3"),
    ]
    assert view.history_base_path == "/health/indexers/prowlarr"
