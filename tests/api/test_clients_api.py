"""Tests for download client API error handling."""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

import pytest

from pullbox.core.encryption import decrypt_secret, encrypt_secret
from pullbox.models.client import DownloadClientConfig
from pullbox.models.download import DownloadClientType
from pullbox.providers.base import ProviderHealthResult
from pullbox.services.auth_service import SESSION_COOKIE_NAME, AuthService

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytest_plugins = ["conftest_security"]


def _client_payload(
    *,
    name: str = "SABnzbd",
    client_type: str = "sabnzbd",
    url: str = "http://localhost:8080",
    **overrides: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": name,
        "client_type": client_type,
        "url": url,
        "enabled": True,
        "priority": 50,
    }
    payload.update(overrides)
    return payload


def _csrf_header_for(client: AsyncClient) -> dict[str, str]:
    token = client.cookies.get(SESSION_COOKIE_NAME)
    csrf = AuthService.get_csrf_token_from_session(token) or ""
    return {"X-CSRF-Token": csrf}


@pytest.mark.asyncio
class TestClientCrud:
    async def test_list_orders_by_priority_then_name_and_redacts_secret_values(
        self,
        authenticated_client: AsyncClient,
        sec_db: async_sessionmaker[AsyncSession],
    ) -> None:
        async with sec_db() as session:
            session.add_all(
                [
                    DownloadClientConfig(
                        name="Zulu NZBGet",
                        client_type=DownloadClientType.NZBGET,
                        url="http://localhost:6789",
                        enabled=True,
                        priority=20,
                        username="nzbget",
                        password=encrypt_secret("nzb-password"),
                    ),
                    DownloadClientConfig(
                        name="Alpha SAB",
                        client_type=DownloadClientType.SABNZBD,
                        url="http://localhost:8080",
                        enabled=True,
                        priority=20,
                        api_key=encrypt_secret("sab-key"),
                    ),
                    DownloadClientConfig(
                        name="qBit",
                        client_type=DownloadClientType.QBITTORRENT,
                        url="http://localhost:8081",
                        enabled=False,
                        priority=80,
                        username="admin",
                        password=encrypt_secret("qbit-password"),
                    ),
                ]
            )
            await session.commit()

        resp = await authenticated_client.get("/api/v1/clients")

        assert resp.status_code == 200
        data = resp.json()
        assert [item["name"] for item in data] == ["Alpha SAB", "Zulu NZBGet", "qBit"]
        assert data[0]["has_api_key"] is True
        assert data[0]["has_password"] is False
        assert data[1]["has_api_key"] is False
        assert data[1]["has_password"] is True
        assert data[2]["enabled"] is False
        assert all("api_key" not in item for item in data)
        assert all("password" not in item for item in data)

    async def test_create_encrypts_secret_and_rejects_duplicate_client_type(
        self,
        authenticated_client: AsyncClient,
        sec_db: async_sessionmaker[AsyncSession],
    ) -> None:
        resp = await authenticated_client.post(
            "/api/v1/clients",
            json=_client_payload(name="SAB", api_key="raw-sab-key", category="comics"),
            headers=_csrf_header_for(authenticated_client),
        )

        assert resp.status_code == 201
        created = resp.json()
        assert created["name"] == "SAB"
        assert created["has_api_key"] is True
        assert "api_key" not in created

        async with sec_db() as session:
            row = await session.get(DownloadClientConfig, created["id"])
            assert row is not None
            assert row.api_key is not None
            assert row.api_key != "raw-sab-key"
            assert decrypt_secret(row.api_key) == "raw-sab-key"
            assert row.category == "comics"

        duplicate = await authenticated_client.post(
            "/api/v1/clients",
            json=_client_payload(name="Second SAB", api_key="other-key"),
            headers=_csrf_header_for(authenticated_client),
        )

        assert duplicate.status_code == 422
        assert "already configured" in duplicate.text

    async def test_update_preserves_blank_password_and_clears_blank_api_key(
        self,
        authenticated_client: AsyncClient,
        sec_db: async_sessionmaker[AsyncSession],
    ) -> None:
        async with sec_db() as session:
            client = DownloadClientConfig(
                name="qBit",
                client_type=DownloadClientType.QBITTORRENT,
                url="http://localhost:8081",
                enabled=True,
                priority=50,
                api_key=encrypt_secret("legacy-key"),
                username="admin",
                password=encrypt_secret("keep-password"),
                category="old",
            )
            session.add(client)
            await session.commit()
            await session.refresh(client)
            client_id = client.id

        resp = await authenticated_client.put(
            f"/api/v1/clients/{client_id}",
            json={
                "name": "Updated qBit",
                "priority": 10,
                "api_key": "",
                "password": "",
                "category": "new",
            },
            headers=_csrf_header_for(authenticated_client),
        )

        assert resp.status_code == 200
        updated = resp.json()
        assert updated["name"] == "Updated qBit"
        assert updated["priority"] == 10
        assert updated["has_api_key"] is False
        assert updated["has_password"] is True
        assert updated["category"] == "new"

        async with sec_db() as session:
            row = await session.get(DownloadClientConfig, client_id)
            assert row is not None
            assert row.api_key == ""
            assert row.password is not None
            assert decrypt_secret(row.password) == "keep-password"

    async def test_delete_removes_client_and_missing_client_returns_not_found(
        self,
        authenticated_client: AsyncClient,
        sec_db: async_sessionmaker[AsyncSession],
    ) -> None:
        async with sec_db() as session:
            client = DownloadClientConfig(
                name="Delete Me",
                client_type=DownloadClientType.DELUGE,
                url="http://localhost:8112",
                enabled=True,
                priority=50,
                password=encrypt_secret("deluge-password"),
            )
            session.add(client)
            await session.commit()
            await session.refresh(client)
            client_id = client.id

        delete_resp = await authenticated_client.delete(
            f"/api/v1/clients/{client_id}",
            headers=_csrf_header_for(authenticated_client),
        )

        assert delete_resp.status_code == 204

        get_resp = await authenticated_client.get(f"/api/v1/clients/{client_id}")
        assert get_resp.status_code == 404

        second_delete = await authenticated_client.delete(
            f"/api/v1/clients/{client_id}",
            headers=_csrf_header_for(authenticated_client),
        )
        assert second_delete.status_code == 404


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

    async def test_inline_edit_test_reuses_saved_credentials_when_form_secrets_blank(
        self,
        authenticated_client: AsyncClient,
        sec_db: async_sessionmaker[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        constructed: dict[str, object] = {}

        async with sec_db() as session:
            client = DownloadClientConfig(
                name="Existing qBit",
                client_type=DownloadClientType.QBITTORRENT,
                url="http://localhost:8081",
                enabled=True,
                priority=50,
                username="saved-user",
                password=encrypt_secret("saved-password"),
                category="comics",
            )
            session.add(client)
            await session.commit()
            await session.refresh(client)
            client_id = client.id

        def _capture_init(self, **kwargs: object) -> None:
            constructed.update(kwargs)

        async def _healthy_test(_self) -> ProviderHealthResult:
            return ProviderHealthResult(
                healthy=True,
                message="qBittorrent is reachable",
                response_time_ms=12.5,
            )

        monkeypatch.setattr(
            "pullbox.providers.download.qbittorrent.QBittorrentClient.__init__",
            _capture_init,
        )
        monkeypatch.setattr(
            "pullbox.providers.download.qbittorrent.QBittorrentClient.test_connection",
            _healthy_test,
        )

        resp = await authenticated_client.post(
            "/api/v1/clients/test",
            params={"existing_id": client_id},
            json=_client_payload(
                name="Existing qBit",
                client_type="qbittorrent",
                url="http://localhost:8081",
                username="",
                password="",
                category="comics",
            ),
            headers=_csrf_header_for(authenticated_client),
        )

        assert resp.status_code == 200
        assert resp.json() == {
            "healthy": True,
            "message": "qBittorrent is reachable",
            "response_time_ms": 12.5,
        }
        assert constructed["username"] == "saved-user"
        assert constructed["password"] == "saved-password"
        assert constructed["category"] == "comics"
