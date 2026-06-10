"""Tests for the temporary debug-logging support endpoints."""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import UTC, datetime, timedelta

import pytest

from pullbox.models.config import SystemConfig
from pullbox.services.auth_service import SESSION_COOKIE_NAME, AuthService

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

pytest_plugins = ["conftest_security"]

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-debug-logging")
os.environ.setdefault("PULLBOX_DATA_DIR", tempfile.mkdtemp())


def _csrf_header_for(client) -> dict[str, str]:  # type: ignore[no-untyped-def]
    token = client.cookies.get(SESSION_COOKIE_NAME) or ""
    csrf = AuthService.get_csrf_token_from_session(token) or ""
    return {"X-CSRF-Token": csrf}


@pytest.mark.asyncio
class TestDebugLoggingApi:
    """Support endpoints should persist, report, and expire overrides correctly."""

    async def test_enable_debug_logging_defaults_to_15_minutes(
        self,
        authenticated_client,
        sec_db,
        monkeypatch,
    ) -> None:  # type: ignore[no-untyped-def]
        reconfigured: list[str] = []
        monkeypatch.setattr(
            "pullbox.logging.reconfigure_logging_runtime",
            lambda *, log_level: reconfigured.append(log_level),
        )

        response = await authenticated_client.post(
            "/api/v1/system/debug-logging",
            headers=_csrf_header_for(authenticated_client),
            json={},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["active"] is True
        assert body["level"] == "debug"
        assert body["remaining_minutes"] == 15
        assert reconfigured == ["debug"]

        async with sec_db() as session:
            result = await session.get(SystemConfig, "log_level_override")
            expires = await session.get(SystemConfig, "log_level_override_expires")
            assert result is not None
            assert result.value == "debug"
            assert expires is not None

    async def test_status_read_clears_expired_override(
        self,
        authenticated_client,
        sec_db,
        monkeypatch,
    ) -> None:  # type: ignore[no-untyped-def]
        async with sec_db() as session:
            session.add_all(
                [
                    SystemConfig(key="log_level", value="info", value_type="string"),
                    SystemConfig(key="log_level_override", value="debug", value_type="string"),
                    SystemConfig(
                        key="log_level_override_expires",
                        value=(datetime.now(UTC) - timedelta(minutes=5)).isoformat(),
                        value_type="string",
                    ),
                    SystemConfig(key="log_level_base", value="info", value_type="string"),
                ]
            )
            await session.commit()

        reconfigured: list[str] = []
        monkeypatch.setattr(
            "pullbox.services.debug_logging_service.reconfigure_logging_runtime",
            lambda *, log_level: reconfigured.append(log_level),
        )

        response = await authenticated_client.get(
            "/api/v1/system/debug-logging",
            headers=_csrf_header_for(authenticated_client),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["active"] is False
        assert body["base_level"] == "info"
        assert reconfigured == ["info"]

        async with sec_db() as session:
            assert await session.get(SystemConfig, "log_level_override") is None
            assert await session.get(SystemConfig, "log_level_override_expires") is None
            assert await session.get(SystemConfig, "log_level_base") is None
