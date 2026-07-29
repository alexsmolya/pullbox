"""API contracts for closed native artifact-host settings."""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

from sqlalchemy import select

from pullbox.core.encryption import is_encrypted
from pullbox.models.direct_acquisition import DirectArtifactHostKind, DirectHostConfig
from pullbox.services.auth_service import SESSION_COOKIE_NAME, AuthService

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
pytest_plugins = ["conftest_security"]


def _csrf_header(client: AsyncClient) -> dict[str, str]:
    session_token = client.cookies.get(SESSION_COOKIE_NAME)
    return {"X-CSRF-Token": AuthService.get_csrf_token_from_session(session_token) or ""}


async def test_host_settings_list_exposes_closed_registry_without_secrets(
    authenticated_client: AsyncClient,
) -> None:
    response = await authenticated_client.get("/api/v1/direct-hosts")

    assert response.status_code == 200
    payload = response.json()
    assert [item["host_kind"] for item in payload] == [
        host_kind.value for host_kind in DirectArtifactHostKind
    ]
    assert all(item["id"] is None for item in payload)
    pixeldrain = next(item for item in payload if item["host_kind"] == "pixeldrain")
    assert pixeldrain["allowed_credential_fields"] == ["api_key"]
    mega = next(item for item in payload if item["host_kind"] == "mega")
    assert mega["allowed_credential_fields"] == ["session"]
    mediafire = next(item for item in payload if item["host_kind"] == "mediafire")
    assert mediafire["allowed_credential_fields"] == []
    datanodes = next(item for item in payload if item["host_kind"] == "datanodes")
    assert datanodes["allowed_credential_fields"] == ["username", "password"]
    assert "credential_updates" not in response.text


async def test_host_setting_update_encrypts_and_never_returns_credentials(
    authenticated_client: AsyncClient,
    sec_db: async_sessionmaker[AsyncSession],
) -> None:
    secret = "private-pixeldrain-api-key"
    response = await authenticated_client.patch(
        "/api/v1/direct-hosts/pixeldrain",
        headers=_csrf_header(authenticated_client),
        json={
            "enabled": True,
            "preference": 10,
            "credential_updates": {"api_key": secret},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    assert payload["credentials_configured"] is True
    assert payload["configured_credential_fields"] == ["api_key"]
    assert secret not in response.text
    async with sec_db() as session:
        stored = (
            await session.execute(
                select(DirectHostConfig).where(
                    DirectHostConfig.host_kind == DirectArtifactHostKind.PIXELDRAIN
                )
            )
        ).scalar_one()
        assert is_encrypted(str(stored.encrypted_credentials["api_key"]))


async def test_account_required_host_rejects_enable_without_session(
    authenticated_client: AsyncClient,
) -> None:
    response = await authenticated_client.patch(
        "/api/v1/direct-hosts/terabox",
        headers=_csrf_header(authenticated_client),
        json={"enabled": True},
    )

    assert response.status_code == 422
    assert "requires an account session" in response.text


async def test_mega_setting_encrypts_session_without_returning_it(
    authenticated_client: AsyncClient,
    sec_db: async_sessionmaker[AsyncSession],
) -> None:
    session_secret = "mega-revocable-session"
    response = await authenticated_client.patch(
        "/api/v1/direct-hosts/mega",
        headers=_csrf_header(authenticated_client),
        json={
            "enabled": True,
            "credential_updates": {"session": session_secret},
        },
    )

    assert response.status_code == 200
    assert response.json()["configured_credential_fields"] == ["session"]
    assert session_secret not in response.text
    async with sec_db() as session:
        stored = (
            await session.execute(
                select(DirectHostConfig).where(
                    DirectHostConfig.host_kind == DirectArtifactHostKind.MEGA
                )
            )
        ).scalar_one()
        assert is_encrypted(str(stored.encrypted_credentials["session"]))


async def test_mega_setting_rejects_obsolete_application_key(
    authenticated_client: AsyncClient,
) -> None:
    response = await authenticated_client.patch(
        "/api/v1/direct-hosts/mega",
        headers=_csrf_header(authenticated_client),
        json={
            "enabled": True,
            "credential_updates": {"app_key": "obsolete-application-key"},
        },
    )

    assert response.status_code == 422
    assert "Unsupported credential field" in response.text


async def test_datanodes_setting_rejects_unverified_premium_session(
    authenticated_client: AsyncClient,
) -> None:
    response = await authenticated_client.patch(
        "/api/v1/direct-hosts/datanodes",
        headers=_csrf_header(authenticated_client),
        json={
            "enabled": True,
            "credential_updates": {"premium_session": "unverified-session"},
        },
    )

    assert response.status_code == 422
    assert "Unsupported credential field" in response.text


async def test_datanodes_setting_requires_and_encrypts_complete_credentials(
    authenticated_client: AsyncClient,
    sec_db: async_sessionmaker[AsyncSession],
) -> None:
    incomplete = await authenticated_client.patch(
        "/api/v1/direct-hosts/datanodes",
        headers=_csrf_header(authenticated_client),
        json={
            "enabled": True,
            "credential_updates": {"username": "reader@example.test"},
        },
    )

    assert incomplete.status_code == 422
    assert "both username and password" in incomplete.text

    password = "private-datanodes-password"
    response = await authenticated_client.patch(
        "/api/v1/direct-hosts/datanodes",
        headers=_csrf_header(authenticated_client),
        json={
            "enabled": True,
            "credential_updates": {
                "username": "reader@example.test",
                "password": password,
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["configured_credential_fields"] == ["password", "username"]
    assert "reader@example.test" not in response.text
    assert password not in response.text
    async with sec_db() as session:
        stored = (
            await session.execute(
                select(DirectHostConfig).where(
                    DirectHostConfig.host_kind == DirectArtifactHostKind.DATANODES
                )
            )
        ).scalar_one()
        assert is_encrypted(str(stored.encrypted_credentials["username"]))
        assert is_encrypted(str(stored.encrypted_credentials["password"]))


async def test_host_setting_routes_require_interactive_authentication(
    unauthenticated_client: AsyncClient,
) -> None:
    assert (await unauthenticated_client.get("/api/v1/direct-hosts")).status_code == 401
