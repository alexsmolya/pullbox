"""Tests for anonymous usage-stats telemetry payloads."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

import pullbox
from pullbox.models.config import SystemConfig
from pullbox.models.import_job import ImportJob, ImportJobStatus, ImportSourceType
from pullbox.models.indexer import IndexerConfig, IndexerType
from pullbox.models.issue import Issue
from pullbox.models.series import Series, SeriesStatus
from pullbox.services.usage_stats_telemetry import (
    UsageStatsTelemetryClient,
    build_usage_stats_payload,
)


async def test_build_usage_stats_payload_collects_anonymous_install_stats(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(pullbox, "STARTED_AT", datetime.now(UTC) - timedelta(days=3, hours=12))

    series = Series(
        title="Absolute Wonder Woman",
        sort_title="Absolute Wonder Woman",
        status=SeriesStatus.CONTINUING,
        issue_count=2,
        monitored=True,
    )
    db_session.add(series)
    await db_session.flush()
    db_session.add_all(
        [
            Issue(series_id=series.id, issue_number=1.0),
            Issue(series_id=series.id, issue_number=2.0),
            IndexerConfig(
                name="Enabled Indexer",
                indexer_type=IndexerType.TORZNAB,
                url="https://indexer.example.test",
                api_key="secret",
                enabled=True,
            ),
            IndexerConfig(
                name="Disabled Indexer",
                indexer_type=IndexerType.NEWZNAB,
                url="https://disabled.example.test",
                api_key="secret",
                enabled=False,
            ),
            ImportJob(
                source_path="/imports/comics",
                source_type=ImportSourceType.FILESYSTEM,
                status=ImportJobStatus.COMPLETED,
            ),
            SystemConfig(key="usage_stats_instance_id", value="install-id", value_type="string"),
        ]
    )
    await db_session.flush()

    payload = await build_usage_stats_payload(db_session)

    assert payload["instance_id"] == "install-id"
    assert payload["pullbox_version"] == pullbox.__version__
    assert payload["platform"]
    assert payload["os"]
    assert payload["python_version"]
    assert payload["db_engine"] == "sqlite"
    assert payload["series_count"] == 1
    assert payload["issues_tracked"] == 2
    assert payload["active_indexers"] == 1
    assert payload["import_completed"] is True
    assert payload["uptime_days"] == pytest.approx(3.5, abs=0.01)


async def test_telemetry_client_posts_payload_to_pullbox_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PULLBOX_DATA_API_BASE_URL", "https://data.example.test/root/")
    from pullbox.config import get_settings

    get_settings.cache_clear()
    seen_requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return httpx.Response(202, json={"accepted": True})

    payload: dict[str, Any] = {
        "instance_id": "install-id",
        "pullbox_version": "0.7.5-dev",
        "platform": "macOS",
        "os": "Darwin",
        "python_version": "3.14.0",
        "db_engine": "sqlite",
        "series_count": 12,
        "issues_tracked": 321,
        "active_indexers": 2,
        "import_completed": True,
        "uptime_days": 1.25,
    }

    client = UsageStatsTelemetryClient(transport=httpx.MockTransport(handler))

    await client.send(payload)

    assert len(seen_requests) == 1
    request = seen_requests[0]
    assert str(request.url) == "https://data.example.test/root/api/v1/telemetry"
    assert request.headers["user-agent"] == f"Pullbox/{pullbox.__version__}"
    assert request.headers["content-type"] == "application/json"
    assert request.read() == httpx.Request("POST", "https://unused", json=payload).read()


async def test_telemetry_client_raises_for_upstream_errors() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "unavailable"})

    client = UsageStatsTelemetryClient(
        base_url="https://data.example.test",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(RuntimeError, match="Telemetry request failed"):
        await client.send({"instance_id": "install-id"})
