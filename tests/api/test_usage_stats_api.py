"""Focused API coverage for install-level anonymous usage stats preference."""

from __future__ import annotations

import os
import sys
from uuid import UUID

import pytest

from pullbox.models.config import SystemConfig
from pullbox.services.auth_service import SESSION_COOKIE_NAME, AuthService

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

pytest_plugins = ["conftest_security"]

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-usage-stats-api")


@pytest.mark.asyncio
async def test_usage_stats_preference_defaults_to_unknown(
    authenticated_client,
    sec_db,
) -> None:  # type: ignore[no-untyped-def]
    response = await authenticated_client.get("/api/v1/system/usage-stats")

    assert response.status_code == 200
    assert response.json() == {
        "consent": "unknown",
        "enabled": False,
        "prompt_pending": True,
    }

    async with sec_db() as session:
        assert await session.get(SystemConfig, "usage_stats_instance_id") is None


@pytest.mark.asyncio
async def test_usage_stats_preference_update_round_trip(
    authenticated_client,
    sec_db,
) -> None:  # type: ignore[no-untyped-def]
    session_token = authenticated_client.cookies.get(SESSION_COOKIE_NAME)
    assert session_token is not None
    csrf_token = AuthService.get_csrf_token_from_session(session_token)
    assert csrf_token is not None

    update = await authenticated_client.put(
        "/api/v1/system/usage-stats",
        json={"enabled": True},
        headers={"X-CSRF-Token": csrf_token},
    )

    assert update.status_code == 200
    assert update.json() == {
        "consent": "enabled",
        "enabled": True,
        "prompt_pending": False,
    }

    async with sec_db() as session:
        instance_config = await session.get(SystemConfig, "usage_stats_instance_id")
        assert instance_config is not None
        assert instance_config.value_type == "string"
        assert str(UUID(instance_config.value)) == instance_config.value

    fetch = await authenticated_client.get("/api/v1/system/usage-stats")
    assert fetch.status_code == 200
    assert fetch.json() == {
        "consent": "enabled",
        "enabled": True,
        "prompt_pending": False,
    }


@pytest.mark.asyncio
async def test_usage_stats_instance_id_persists_across_disable_and_reenable(
    authenticated_client,
    sec_db,
) -> None:  # type: ignore[no-untyped-def]
    session_token = authenticated_client.cookies.get(SESSION_COOKIE_NAME)
    assert session_token is not None
    csrf_token = AuthService.get_csrf_token_from_session(session_token)
    assert csrf_token is not None
    headers = {"X-CSRF-Token": csrf_token}

    enabled = await authenticated_client.put(
        "/api/v1/system/usage-stats",
        json={"enabled": True},
        headers=headers,
    )
    assert enabled.status_code == 200

    async with sec_db() as session:
        first_config = await session.get(SystemConfig, "usage_stats_instance_id")
        assert first_config is not None
        first_instance_id = first_config.value

    disabled = await authenticated_client.put(
        "/api/v1/system/usage-stats",
        json={"enabled": False},
        headers=headers,
    )
    assert disabled.status_code == 200

    reenabled = await authenticated_client.put(
        "/api/v1/system/usage-stats",
        json={"enabled": True},
        headers=headers,
    )
    assert reenabled.status_code == 200

    async with sec_db() as session:
        current_config = await session.get(SystemConfig, "usage_stats_instance_id")
        assert current_config is not None
        assert current_config.value == first_instance_id
