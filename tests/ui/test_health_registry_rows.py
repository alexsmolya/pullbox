"""Tests for health registry summary row builders."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pullbox.models.client import DownloadClientConfig
from pullbox.models.config import SystemConfig
from pullbox.models.direct_acquisition import (
    DirectArtifactHostKind,
    DirectHostConfig,
    DirectHostReachabilityState,
    DirectProviderConfig,
    DirectProviderState,
)
from pullbox.models.download import DownloadClientType
from pullbox.models.health import HealthCurrentStatus, HealthStatus
from pullbox.models.indexer import IndexerConfig, IndexerType


@pytest.mark.asyncio
async def test_build_download_client_registry_rows_uses_enabled_configs_and_latest_health(
    db_session,
) -> None:  # type: ignore[no-untyped-def]
    from pullbox.ui.health_registry_rows import build_download_client_registry_rows

    now = datetime.now(UTC)
    enabled = DownloadClientConfig(
        name="SAB Main",
        client_type=DownloadClientType.SABNZBD,
        url="https://sab.example:9090/api",
        enabled=True,
    )
    disabled = DownloadClientConfig(
        name="Disabled",
        client_type=DownloadClientType.NZBGET,
        url="http://disabled.example:6789",
        enabled=False,
    )
    db_session.add_all([enabled, disabled])
    await db_session.flush()
    db_session.add(
        HealthCurrentStatus(
            component="download_clients",
            current_key="summary",
            check_name="summary",
            subject_key=str(enabled.id),
            subject_key_norm=str(enabled.id),
            status=HealthStatus.HEALTHY,
            message="OK",
            response_time_ms=42.0,
            checked_at=now - timedelta(minutes=3),
            is_summary=True,
        )
    )
    await db_session.flush()

    rows = await build_download_client_registry_rows(
        db_session,
        current_time=now,
        relative_time_label=lambda value, reference: (
            f"{int((reference - value).total_seconds() // 60)}m ago"
        ),
        download_client_type_label=lambda value: value.upper(),
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.display_name == "SAB Main"
    assert row.kind_label == "SABNZBD"
    assert row.detail_label == "HTTPS · sab.example:9090"
    assert row.response_label == "42ms"
    assert row.last_check_label == "3m ago"
    assert row.status_label == "Healthy"
    assert row.href == f"/health/download_clients/{enabled.id}"


@pytest.mark.asyncio
async def test_download_client_registry_includes_direct_provider_and_artifact_host(
    db_session,
) -> None:  # type: ignore[no-untyped-def]
    from pullbox.ui.health_registry_rows import build_download_client_registry_rows

    now = datetime.now(UTC)
    provider = DirectProviderConfig(
        provider_id="pullbox.getcomics",
        display_name="GetComics",
        endpoint="https://getcomics.example:8780",
        enabled=True,
        state=DirectProviderState.HEALTHY,
    )
    host = DirectHostConfig(
        host_kind=DirectArtifactHostKind.PIXELDRAIN,
        enabled=True,
        preference=10,
        reachability_state=DirectHostReachabilityState.REACHABLE,
    )
    db_session.add_all([provider, host])
    await db_session.flush()
    db_session.add_all(
        [
            HealthCurrentStatus(
                component="download_clients",
                current_key="summary",
                check_name="direct_provider_summary",
                subject_key=f"direct-provider:{provider.id}",
                subject_key_norm=f"direct-provider:{provider.id}",
                status=HealthStatus.HEALTHY,
                message="OK",
                checked_at=now - timedelta(minutes=1),
                is_summary=True,
            ),
            HealthCurrentStatus(
                component="download_clients",
                current_key="summary",
                check_name="artifact_host_summary",
                subject_key="artifact-host:pixeldrain",
                subject_key_norm="artifact-host:pixeldrain",
                status=HealthStatus.HEALTHY,
                message="OK",
                checked_at=now - timedelta(minutes=2),
                is_summary=True,
            ),
        ]
    )
    await db_session.flush()

    rows = await build_download_client_registry_rows(
        db_session,
        current_time=now,
        relative_time_label=lambda value, reference: (
            f"{int((reference - value).total_seconds() // 60)}m ago"
        ),
        download_client_type_label=lambda value: value.upper(),
    )

    assert [(row.display_name, row.kind_label) for row in rows] == [
        ("GetComics", "Direct Provider"),
        ("Pixeldrain", "Artifact Host"),
    ]
    assert rows[0].detail_label == "HTTPS · getcomics.example:8780"
    assert rows[1].detail_label == "Preference 10"
    assert rows[0].href == "/settings?tab=direct"
    assert rows[1].href == "/settings?tab=direct"


@pytest.mark.asyncio
async def test_build_indexer_registry_rows_splits_search_proxies_and_enabled_indexers(
    db_session,
) -> None:  # type: ignore[no-untyped-def]
    from pullbox.ui.health_registry_rows import build_indexer_registry_rows

    now = datetime.now(UTC)
    db_session.add_all(
        [
            SystemConfig(key="prowlarr_url", value="http://prowlarr.example:9696"),
            SystemConfig(key="prowlarr_api_key", value="secret"),
            SystemConfig(key="jackett_url", value="http://jackett.example:9117"),
            SystemConfig(key="jackett_api_key", value="secret"),
        ]
    )
    indexer = IndexerConfig(
        name="NZB Cave",
        indexer_type=IndexerType.NEWZNAB,
        url="https://nzb.example/api",
        api_key="secret",
        enabled=True,
    )
    disabled = IndexerConfig(
        name="Disabled",
        indexer_type=IndexerType.TORZNAB,
        url="https://disabled.example/api",
        api_key="secret",
        enabled=False,
    )
    db_session.add_all([indexer, disabled])
    await db_session.flush()
    db_session.add_all(
        [
            HealthCurrentStatus(
                component="indexers",
                current_key="summary",
                check_name="summary",
                subject_key="prowlarr",
                subject_key_norm="prowlarr",
                status=HealthStatus.DEGRADED,
                message="Slow",
                details_json='{"indexer_count": 7}',
                response_time_ms=250.0,
                checked_at=now - timedelta(minutes=4),
                is_summary=True,
            ),
            HealthCurrentStatus(
                component="indexers",
                current_key="summary",
                check_name="summary",
                subject_key="jackett",
                subject_key_norm="jackett",
                status=HealthStatus.HEALTHY,
                message="OK",
                details_json='{"indexer_count": 2}',
                response_time_ms=120.0,
                checked_at=now - timedelta(minutes=1),
                is_summary=True,
            ),
            HealthCurrentStatus(
                component="indexers",
                current_key="summary",
                check_name="summary",
                subject_key=str(indexer.id),
                subject_key_norm=str(indexer.id),
                status=HealthStatus.HEALTHY,
                message="OK",
                response_time_ms=88.0,
                checked_at=now - timedelta(minutes=2),
                is_summary=True,
            ),
        ]
    )
    await db_session.flush()

    proxy_rows, rows = await build_indexer_registry_rows(
        db_session,
        current_time=now,
        relative_time_label=lambda value, reference: (
            f"{int((reference - value).total_seconds() // 60)}m ago"
        ),
    )

    assert len(proxy_rows) == 2
    prowlarr_row, jackett_row = proxy_rows
    assert prowlarr_row.display_name == "Prowlarr"
    assert prowlarr_row.kind_label == "Proxy"
    assert prowlarr_row.detail_label == "HTTP · prowlarr.example:9696 · 7 indexers"
    assert prowlarr_row.status_label == "Degraded"
    assert prowlarr_row.href == "/health/indexers/prowlarr"
    assert jackett_row.display_name == "Jackett"
    assert jackett_row.detail_label == "HTTP · jackett.example:9117 · 2 indexers"
    assert jackett_row.status_label == "Healthy"
    assert jackett_row.href == "/health/indexers/jackett"

    assert len(rows) == 1
    row = rows[0]
    assert row.display_name == "NZB Cave"
    assert row.kind_label == "Usenet"
    assert row.detail_label == "Newznab"
    assert row.response_label == "88ms"
    assert row.last_check_label == "2m ago"
    assert row.href == f"/health/indexers/{indexer.id}"
