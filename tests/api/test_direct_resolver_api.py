"""API contracts for the optional shared browser challenge resolver."""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

import pytest

from pullbox.api.v1 import direct_resolver as direct_resolver_api
from pullbox.models.direct_acquisition import DirectResolverConfig
from pullbox.providers.direct.endpoint import ValidatedProviderEndpoint
from pullbox.providers.direct.resolver import DirectResolverResult
from pullbox.services.auth_service import SESSION_COOKIE_NAME, AuthService

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
pytest_plugins = ["conftest_security"]

AUTH_VALUE = "Bearer api-resolver-secret"


def _csrf_header(client: AsyncClient) -> dict[str, str]:
    session_token = client.cookies.get(SESSION_COOKIE_NAME)
    return {"X-CSRF-Token": AuthService.get_csrf_token_from_session(session_token) or ""}


class _ApiResolverClient:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs

    async def validate_endpoint(self) -> ValidatedProviderEndpoint:
        return ValidatedProviderEndpoint(
            url="http://resolver:8191",
            host="resolver",
            port=8191,
            addresses=("172.20.0.9",),
            private_network=True,
            insecure_transport=True,
        )

    async def solve(self, *_args: object, **_kwargs: object) -> DirectResolverResult:
        return DirectResolverResult(
            final_url="https://example.com/",
            status_code=200,
            html="<html>Example Domain</html>",
            cookies=(),
            user_agent="Resolver Browser",
        )

    async def aclose(self) -> None:
        return None


def _factory(**kwargs: object) -> _ApiResolverClient:
    return _ApiResolverClient(**kwargs)


@pytest.fixture(autouse=True)
def _resolver_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(direct_resolver_api, "direct_resolver_client_factory", _factory)


async def test_resolver_api_defaults_to_disabled_and_requires_operator_auth(
    authenticated_client: AsyncClient,
    unauthenticated_client: AsyncClient,
) -> None:
    response = await authenticated_client.get("/api/v1/direct-resolver")

    assert response.status_code == 200
    assert response.json() == {
        "name": "default",
        "endpoint": "",
        "enabled": False,
        "state": "disabled",
        "allow_private_http": False,
        "timeout_seconds": 60,
        "max_concurrency": 1,
        "auth_headers_configured": False,
        "auth_header_names": [],
        "last_health_at": None,
        "last_tested_at": None,
        "last_error_code": None,
    }
    assert (await unauthenticated_client.get("/api/v1/direct-resolver")).status_code == 401


async def test_resolver_api_updates_tests_and_never_returns_auth_values(
    authenticated_client: AsyncClient,
    sec_db: async_sessionmaker[AsyncSession],
) -> None:
    headers = _csrf_header(authenticated_client)
    updated = await authenticated_client.patch(
        "/api/v1/direct-resolver",
        headers=headers,
        json={
            "endpoint": "http://resolver:8191",
            "enabled": True,
            "allow_private_http": True,
            "timeout_seconds": 75,
            "max_concurrency": 2,
            "authentication_headers": {"Authorization": AUTH_VALUE},
        },
    )

    assert updated.status_code == 200
    assert updated.json()["state"] == "unknown"
    assert updated.json()["auth_header_names"] == ["Authorization"]
    assert AUTH_VALUE not in updated.text

    tested = await authenticated_client.post(
        "/api/v1/direct-resolver/test",
        headers=headers,
    )
    assert tested.status_code == 200
    assert tested.json()["usable"] is True
    assert tested.json()["state"] == "healthy"
    assert "standard /v1" in tested.json()["message"]
    assert AUTH_VALUE not in tested.text

    refreshed = await authenticated_client.get("/api/v1/direct-resolver")
    assert refreshed.json()["state"] == "healthy"
    async with sec_db() as session:
        row = await session.get(DirectResolverConfig, 1)
        assert row is not None
        assert AUTH_VALUE not in str(row.encrypted_auth_headers)


async def test_resolver_api_rejects_cookie_or_host_header_authority(
    authenticated_client: AsyncClient,
) -> None:
    headers = _csrf_header(authenticated_client)
    for forbidden in ("Cookie", "Host", "Proxy-Authorization"):
        response = await authenticated_client.patch(
            "/api/v1/direct-resolver",
            headers=headers,
            json={
                "endpoint": "http://resolver:8191",
                "enabled": True,
                "allow_private_http": True,
                "authentication_headers": {forbidden: "must-not-pass"},
            },
        )
        assert response.status_code == 422
        assert "must-not-pass" not in response.text
