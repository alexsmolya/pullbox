"""Focused API tests for runtime utility logging configuration."""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

import pytest

from pullbox.core.config_resolver import get_runtime_settings
from pullbox.services.auth_service import SESSION_COOKIE_NAME, AuthService

if TYPE_CHECKING:
    from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

pytest_plugins = ["conftest_security"]

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-utility-logging-api")


def _csrf_header_for(client) -> dict[str, str]:  # type: ignore[no-untyped-def]
    token = client.cookies.get(SESSION_COOKIE_NAME) or ""
    csrf = AuthService.get_csrf_token_from_session(token) or ""
    return {"X-CSRF-Token": csrf}


@pytest.mark.asyncio
async def test_updating_utility_log_level_reconfigures_runtime_logger(
    authenticated_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # type: ignore[no-untyped-def]
    calls: list[tuple[Path, str]] = []

    def _fake_reconfigure(log_dir: Path, level: str = "INFO") -> None:
        calls.append((log_dir, level))

    monkeypatch.setattr(
        "pullbox.utilities.logging_config.configure_utility_logging_runtime",
        _fake_reconfigure,
    )

    response = await authenticated_client.put(
        "/api/v1/config",
        json={"values": {"utility_log_level": "ERROR"}},
        headers=_csrf_header_for(authenticated_client),
    )

    assert response.status_code == 200
    assert calls == [(get_runtime_settings().logs_dir, "ERROR")]
