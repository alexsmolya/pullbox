"""Baseline API coverage for outbound usage-stats telemetry hooks."""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, Mock, patch

import pytest
from sqlalchemy import select

from pullbox.models.config import SystemConfig
from pullbox.services.auth_service import SESSION_COOKIE_NAME, AuthService

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

pytest_plugins = ["conftest_security"]

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-telemetry-api")


def _csrf_header_for(authenticated_client) -> dict[str, str]:  # type: ignore[no-untyped-def]
    session_token = authenticated_client.cookies.get(SESSION_COOKIE_NAME)
    assert session_token is not None
    csrf_token = AuthService.get_csrf_token_from_session(session_token)
    assert csrf_token is not None
    return {"X-CSRF-Token": csrf_token}


@pytest.mark.asyncio
async def test_enabling_usage_stats_queues_immediate_telemetry_ping(
    authenticated_client,
    sec_db,
) -> None:  # type: ignore[no-untyped-def]
    with patch(
        "pullbox.api.v1.system.queue_usage_stats_ping",
        new_callable=AsyncMock,
    ) as queue_ping:
        response = await authenticated_client.put(
            "/api/v1/system/usage-stats",
            json={"enabled": True},
            headers=_csrf_header_for(authenticated_client),
        )

    assert response.status_code == 200
    queue_ping.assert_awaited_once()
    _, kwargs = queue_ping.await_args
    assert kwargs["session_factory"] is sec_db


@pytest.mark.asyncio
async def test_disabling_usage_stats_does_not_queue_telemetry_ping(
    authenticated_client,
) -> None:  # type: ignore[no-untyped-def]
    with patch(
        "pullbox.api.v1.system.queue_usage_stats_ping",
        new_callable=AsyncMock,
    ) as queue_ping:
        response = await authenticated_client.put(
            "/api/v1/system/usage-stats",
            json={"enabled": False},
            headers=_csrf_header_for(authenticated_client),
        )

    assert response.status_code == 200
    queue_ping.assert_not_awaited()


@pytest.mark.asyncio
async def test_immediate_telemetry_ping_posts_anonymous_payload(
    sec_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # type: ignore[no-untyped-def]
    sent_payloads: list[dict[str, object]] = []

    async def fake_send(self, payload):  # type: ignore[no-untyped-def]
        sent_payloads.append(payload)

    monkeypatch.setattr(
        "pullbox.services.usage_stats_telemetry.UsageStatsTelemetryClient.send",
        fake_send,
    )
    async with sec_db() as session:
        session.add(SystemConfig(key="usage_stats_consent", value="enabled", value_type="string"))
        session.add(
            SystemConfig(key="usage_stats_instance_id", value="install-id", value_type="string")
        )
        await session.commit()

    from pullbox.services.usage_stats_telemetry import send_usage_stats_ping

    await send_usage_stats_ping(session_factory=sec_db)

    assert len(sent_payloads) == 1
    assert sent_payloads[0]["instance_id"] == "install-id"


@pytest.mark.asyncio
async def test_immediate_telemetry_ping_repairs_enabled_consent_without_instance_id(
    sec_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # type: ignore[no-untyped-def]
    sent_payloads: list[dict[str, object]] = []

    async def fake_send(self, payload):  # type: ignore[no-untyped-def]
        sent_payloads.append(payload)

    monkeypatch.setattr(
        "pullbox.services.usage_stats_telemetry.UsageStatsTelemetryClient.send",
        fake_send,
    )
    async with sec_db() as session:
        session.add(SystemConfig(key="usage_stats_consent", value="enabled", value_type="string"))
        session.add(SystemConfig(key="usage_stats_instance_id", value="", value_type="string"))
        await session.commit()

    from pullbox.services.usage_stats_telemetry import send_usage_stats_ping

    await send_usage_stats_ping(session_factory=sec_db)

    assert len(sent_payloads) == 1
    instance_id = sent_payloads[0]["instance_id"]
    assert isinstance(instance_id, str)
    assert instance_id
    async with sec_db() as session:
        persisted = await session.get(SystemConfig, "usage_stats_instance_id")
        assert persisted is not None
        assert persisted.value == instance_id


@pytest.mark.asyncio
async def test_immediate_telemetry_ping_is_skipped_without_enabled_consent(
    sec_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # type: ignore[no-untyped-def]
    send = AsyncMock()
    monkeypatch.setattr(
        "pullbox.services.usage_stats_telemetry.UsageStatsTelemetryClient.send",
        send,
    )
    async with sec_db() as session:
        session.add(SystemConfig(key="usage_stats_consent", value="disabled", value_type="string"))
        session.add(
            SystemConfig(key="usage_stats_instance_id", value="install-id", value_type="string")
        )
        await session.commit()

    from pullbox.services.usage_stats_telemetry import send_usage_stats_ping

    await send_usage_stats_ping(session_factory=sec_db)

    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_immediate_telemetry_ping_logs_failures_at_debug_only(
    sec_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # type: ignore[no-untyped-def]
    async def fail_send(self, payload):  # type: ignore[no-untyped-def]
        raise RuntimeError("upstream unavailable")

    monkeypatch.setattr(
        "pullbox.services.usage_stats_telemetry.UsageStatsTelemetryClient.send",
        fail_send,
    )
    async with sec_db() as session:
        session.add(SystemConfig(key="usage_stats_consent", value="enabled", value_type="string"))
        session.add(
            SystemConfig(key="usage_stats_instance_id", value="install-id", value_type="string")
        )
        await session.commit()

    from pullbox.services import usage_stats_telemetry

    debug = Mock()
    monkeypatch.setattr(usage_stats_telemetry.logger, "debug", debug)

    await usage_stats_telemetry.send_usage_stats_ping(session_factory=sec_db)

    debug.assert_any_call("usage_stats_ping_failed", exc_info=True)


@pytest.mark.asyncio
async def test_enabling_usage_stats_persists_before_background_ping(
    authenticated_client,
    sec_db,
) -> None:  # type: ignore[no-untyped-def]
    async def assert_committed_before_ping(*, session_factory):  # type: ignore[no-untyped-def]
        async with session_factory() as session:
            result = await session.execute(
                select(SystemConfig.value).where(SystemConfig.key == "usage_stats_consent")
            )
            assert result.scalar_one() == "enabled"

    with patch(
        "pullbox.api.v1.system.queue_usage_stats_ping",
        side_effect=assert_committed_before_ping,
    ):
        response = await authenticated_client.put(
            "/api/v1/system/usage-stats",
            json={"enabled": True},
            headers=_csrf_header_for(authenticated_client),
        )

    assert response.status_code == 200
