"""API contracts for manual direct-provider registration and lifecycle."""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING, ClassVar

import pytest

from pullbox.api.v1 import direct_providers as direct_provider_api
from pullbox.models.direct_acquisition import DirectProviderConfig
from pullbox.providers.direct.contract import (
    DIRECT_PROVIDER_PROTOCOL_V1,
    DirectHealthResponse,
    DirectManifestResponse,
)
from pullbox.providers.direct.endpoint import ValidatedProviderEndpoint
from pullbox.services.auth_service import SESSION_COOKIE_NAME, AuthService

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
pytest_plugins = ["conftest_security"]

TOKEN = "api-provider-token-with-sufficient-length"


def _csrf_header(client: AsyncClient) -> dict[str, str]:
    session_token = client.cookies.get(SESSION_COOKIE_NAME)
    return {"X-CSRF-Token": AuthService.get_csrf_token_from_session(session_token) or ""}


def _manifest(
    provider_id: str = "community.api",
    *,
    quota: bool = False,
) -> DirectManifestResponse:
    return DirectManifestResponse.model_validate(
        {
            "protocol_version": DIRECT_PROVIDER_PROTOCOL_V1,
            "provider_id": provider_id,
            "display_name": "API Provider",
            "description": "API route fixture.",
            "provider_version": "1.0.0",
            "supported_protocol_versions": [DIRECT_PROVIDER_PROTOCOL_V1],
            "publisher": "Community",
            "license": "GPL-3.0-or-later",
            "source_domains": ["provider.test"],
            "capabilities": {
                "search": True,
                "resolve": True,
                "health": True,
                "browser_challenge": False,
                "quota": quota,
                "configuration_schema": True,
            },
            "configuration_schema": {
                "type": "object",
                "properties": {
                    "account_token": {
                        "type": "string",
                        "title": "Account token",
                        "x-pullbox-secret": True,
                    }
                },
                "additionalProperties": False,
            },
        }
    )


class _ApiProviderClient:
    manifest_response: ClassVar[DirectManifestResponse] = _manifest()

    def __init__(
        self,
        *,
        endpoint: str,
        bearer_token: str,
        allow_private_http: bool,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.bearer_token = bearer_token
        self.allow_private_http = allow_private_http

    async def validate_endpoint(self) -> ValidatedProviderEndpoint:
        return ValidatedProviderEndpoint(
            url=self.endpoint,
            host="provider",
            port=8780,
            addresses=("172.20.0.8",),
            private_network=True,
            insecure_transport=True,
        )

    async def manifest(self) -> DirectManifestResponse:
        return self.manifest_response

    async def health(self) -> DirectHealthResponse:
        return DirectHealthResponse.model_validate(
            {
                "protocol_version": DIRECT_PROVIDER_PROTOCOL_V1,
                "process_status": "healthy",
                "source_status": "healthy",
                "message": "Ready.",
                "retry_after_seconds": None,
                "diagnostics": {},
            }
        )

    async def aclose(self) -> None:
        return None


def _factory(**kwargs: object) -> _ApiProviderClient:
    return _ApiProviderClient(**kwargs)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _provider_client(monkeypatch: pytest.MonkeyPatch) -> None:
    _ApiProviderClient.manifest_response = _manifest()
    monkeypatch.setattr(direct_provider_api, "direct_provider_client_factory", _factory)


async def test_registration_requires_custom_confirmation_and_never_returns_secrets(
    authenticated_client: AsyncClient,
) -> None:
    headers = _csrf_header(authenticated_client)
    rejected = await authenticated_client.post(
        "/api/v1/direct-providers",
        headers=headers,
        json={
            "endpoint": "http://provider:8780",
            "bearer_token": TOKEN,
            "allow_private_http": True,
            "confirm_custom_provider": False,
        },
    )
    assert rejected.status_code == 409
    assert "custom-provider" in rejected.text

    created = await authenticated_client.post(
        "/api/v1/direct-providers",
        headers=headers,
        json={
            "endpoint": "http://provider:8780",
            "bearer_token": TOKEN,
            "allow_private_http": True,
            "confirm_custom_provider": True,
            "priority": 20,
        },
    )

    assert created.status_code == 201
    payload = created.json()
    assert payload["provider_id"] == "community.api"
    assert payload["enabled"] is False
    assert payload["bearer_token_configured"] is True
    assert "bearer_token" not in payload
    assert TOKEN not in created.text


async def test_provider_lifecycle_lists_updates_tests_enables_and_removes(
    authenticated_client: AsyncClient,
    sec_db: async_sessionmaker[AsyncSession],
) -> None:
    headers = _csrf_header(authenticated_client)
    created_response = await authenticated_client.post(
        "/api/v1/direct-providers",
        headers=headers,
        json={
            "endpoint": "http://provider:8780",
            "bearer_token": TOKEN,
            "allow_private_http": True,
            "confirm_custom_provider": True,
        },
    )
    provider_id = created_response.json()["id"]

    updated = await authenticated_client.patch(
        f"/api/v1/direct-providers/{provider_id}",
        headers=headers,
        json={
            "priority": 5,
            "secret_configuration": {"account_token": "account-secret-value"},
        },
    )
    assert updated.status_code == 200
    assert updated.json()["priority"] == 5
    assert updated.json()["configured_secret_fields"] == ["account_token"]
    assert "account-secret-value" not in updated.text

    tested = await authenticated_client.post(
        f"/api/v1/direct-providers/{provider_id}/test",
        headers=headers,
    )
    assert tested.status_code == 200
    assert tested.json()["usable"] is True

    enabled = await authenticated_client.post(
        f"/api/v1/direct-providers/{provider_id}/enable",
        headers=headers,
    )
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True

    listed = await authenticated_client.get("/api/v1/direct-providers")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [provider_id]

    deleted = await authenticated_client.delete(
        f"/api/v1/direct-providers/{provider_id}",
        headers=headers,
    )
    assert deleted.status_code == 204
    async with sec_db() as session:
        assert await session.get(DirectProviderConfig, provider_id) is None


async def test_provider_routes_require_interactive_authentication(
    unauthenticated_client: AsyncClient,
) -> None:
    assert (await unauthenticated_client.get("/api/v1/direct-providers")).status_code == 401


async def test_quota_telemetry_and_automatic_reserve_are_exposed_and_configurable(
    authenticated_client: AsyncClient,
    sec_db: async_sessionmaker[AsyncSession],
) -> None:
    _ApiProviderClient.manifest_response = _manifest(quota=True)
    headers = _csrf_header(authenticated_client)
    created = await authenticated_client.post(
        "/api/v1/direct-providers",
        headers=headers,
        json={
            "endpoint": "http://provider:8780",
            "bearer_token": TOKEN,
            "allow_private_http": True,
            "confirm_custom_provider": True,
        },
    )
    provider_id = created.json()["id"]
    async with sec_db() as session:
        provider = await session.get(DirectProviderConfig, provider_id)
        assert provider is not None
        provider.configuration_metadata = {
            **provider.configuration_metadata,
            "quota_status": {
                "remaining": 22,
                "limit": 25,
                "window_seconds": 64_800,
                "reset_at": None,
                "observed_at": "2026-07-31T12:00:00+00:00",
            },
        }
        await session.commit()

    listed = await authenticated_client.get("/api/v1/direct-providers")
    payload = listed.json()[0]
    assert payload["quota_supported"] is True
    assert payload["quota_remaining"] == 22
    assert payload["quota_limit"] == 25
    assert payload["quota_window_seconds"] == 64_800
    assert payload["automatic_quota_reserve"] == 5

    updated = await authenticated_client.patch(
        f"/api/v1/direct-providers/{provider_id}",
        headers=headers,
        json={"automatic_quota_reserve": 3},
    )

    assert updated.status_code == 200
    assert updated.json()["automatic_quota_reserve"] == 3
