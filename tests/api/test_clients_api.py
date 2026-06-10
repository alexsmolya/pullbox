"""Tests for download client API error handling."""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

import pytest

from pullbox.core.encryption import encrypt_secret
from pullbox.models.client import DownloadClientConfig
from pullbox.models.download import DownloadClientType
from pullbox.providers.base import ProviderHealthResult
from pullbox.services.auth_service import SESSION_COOKIE_NAME, AuthService

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytest_plugins = ["conftest_security"]


def _csrf_header_for(client: AsyncClient) -> dict[str, str]:
    token = client.cookies.get(SESSION_COOKIE_NAME)
    csrf = AuthService.get_csrf_token_from_session(token) or ""
    return {"X-CSRF-Token": csrf}


@pytest.mark.asyncio
class TestClientTestConnection:
    async def test_successful_client_test_persists_health_and_message(
        self,
        authenticated_client: AsyncClient,
        sec_db: async_sessionmaker[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async with sec_db() as session:
            client = DownloadClientConfig(
                name="Healthy SAB",
                client_type=DownloadClientType.SABNZBD,
                url="http://localhost:8080",
                enabled=True,
                priority=50,
                api_key=encrypt_secret("sab-key"),
            )
            session.add(client)
            await session.commit()
            await session.refresh(client)
            client_id = client.id

        async def _healthy_test(_self) -> ProviderHealthResult:
            return ProviderHealthResult(
                healthy=True,
                message="SABnzbd 4.5.1",
                response_time_ms=41.0,
            )

        monkeypatch.setattr(
            "pullbox.providers.download.sabnzbd.SABnzbdClient.test_connection",
            _healthy_test,
        )

        resp = await authenticated_client.post(
            f"/api/v1/clients/{client_id}/test",
            headers=_csrf_header_for(authenticated_client),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["healthy"] is True
        assert data["message"] == "SABnzbd 4.5.1"

        async with sec_db() as session:
            refreshed = await session.get(DownloadClientConfig, client_id)
            assert refreshed is not None
            assert refreshed.last_success_at is not None
            assert refreshed.last_test_message == "SABnzbd 4.5.1"
            assert refreshed.last_error is None

    async def test_saved_secret_decrypt_failure_returns_failed_result(
        self,
        authenticated_client: AsyncClient,
        sec_db: async_sessionmaker[AsyncSession],
    ) -> None:
        async with sec_db() as session:
            client = DownloadClientConfig(
                name="Broken SAB",
                client_type=DownloadClientType.SABNZBD,
                url="http://localhost:8080",
                enabled=True,
                priority=50,
                api_key="enc:not-a-valid-token",
            )
            session.add(client)
            await session.commit()
            await session.refresh(client)
            client_id = client.id

        resp = await authenticated_client.post(
            f"/api/v1/clients/{client_id}/test",
            headers=_csrf_header_for(authenticated_client),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["healthy"] is False
        assert "could not be decrypted" in data["message"].lower()

        async with sec_db() as session:
            refreshed = await session.get(DownloadClientConfig, client_id)
            assert refreshed is not None
            assert refreshed.last_failure_at is not None
            assert refreshed.last_error is not None
            assert refreshed.last_test_message is not None
            assert "could not be decrypted" in refreshed.last_error.lower()
            assert refreshed.last_test_message == refreshed.last_error
