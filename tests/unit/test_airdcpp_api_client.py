"""Bounded AirDC++ REST client tests using deterministic HTTP fakes."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import httpx
import pytest

from pullbox.providers.airdcpp.api_client import AirDcppApiClient
from pullbox.providers.airdcpp.errors import (
    AirDcppAuthenticationError,
    AirDcppConflictError,
    AirDcppEntityNotFoundError,
    AirDcppPermissionError,
    AirDcppRateLimitError,
    AirDcppResponseError,
    AirDcppUnavailableError,
)

if TYPE_CHECKING:
    from collections.abc import Callable


def _system_info() -> dict[str, object]:
    return {
        "api_version": 1,
        "api_feature_level": 10,
        "client_version": "AirDC++w 2.14.0 x86_64",
        "platform": "linux",
        "path_separator": "/",
    }


def _user() -> dict[str, object]:
    return {
        "username": "pullbox",
        "permissions": [
            "search",
            "download",
            "queue_view",
            "queue_edit",
            "hubs_view",
            "settings_view",
        ],
    }


def _auth() -> dict[str, object]:
    return {
        "session_id": 123,
        "auth_token": "server-bearer-token",
        "token_type": "Bearer",
        "system_info": _system_info(),
        "user": _user(),
        "wizard_pending": False,
    }


def _client(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    max_response_bytes: int = 1_048_576,
) -> AirDcppApiClient:
    return AirDcppApiClient(
        base_url="http://airdcpp.test:5600",
        username="pullbox",
        password="local-password",
        timeout_seconds=15,
        max_response_bytes=max_response_bytes,
        transport=httpx.MockTransport(handler),
    )


async def test_authorize_uses_exact_path_and_bearer_for_read_methods() -> None:
    requests: list[tuple[str, str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path, request.headers.get("authorization")))
        if request.url.path == "/api/v1/sessions/authorize":
            assert json.loads(request.content) == {
                "username": "pullbox",
                "password": "local-password",
            }
            return httpx.Response(200, json={**_auth(), "additive": True})
        if request.url.path == "/api/v1/sessions/self" and request.method == "GET":
            return httpx.Response(200, json={"id": 123, "user": _user()})
        if request.url.path == "/api/v1/system/system_info":
            return httpx.Response(200, json=_system_info())
        if request.url.path == "/api/v1/hubs":
            return httpx.Response(200, json=[])
        if request.url.path == "/api/v1/settings/get":
            assert json.loads(request.content) == {"keys": ["min_search_interval"]}
            return httpx.Response(200, json=[45])
        if request.url.path == "/api/v1/queue/bundles/0/1":
            return httpx.Response(200, json=[])
        if request.url.path == "/api/v1/sessions/self" and request.method == "DELETE":
            return httpx.Response(204)
        raise AssertionError(f"Unexpected request: {request.method} {request.url.path}")

    client = _client(handler)
    auth = await client.authorize()
    session = await client.get_current_session()
    system_info = await client.get_system_info()
    hubs = await client.get_hubs()
    settings = await client.get_settings(["min_search_interval"])
    bundles = await client.get_queue_bundles(start=0, count=1)
    await client.delete_current_session()
    await client.aclose()

    assert auth.session_id == 123
    assert session.user.username == "pullbox"
    assert system_info.api_version == 1
    assert hubs == []
    assert settings == [45]
    assert bundles == []
    assert requests[0] == ("POST", "/api/v1/sessions/authorize", None)
    assert all(auth_header == "Bearer server-bearer-token" for _, _, auth_header in requests[1:])


@pytest.mark.parametrize(
    ("status", "body", "error_type"),
    [
        (401, {"message": "bad local-password"}, AirDcppAuthenticationError),
        (
            403,
            {"error": {"message": "The permission queue_view is required"}},
            AirDcppPermissionError,
        ),
        (404, {"message": "missing private entity"}, AirDcppEntityNotFoundError),
        (409, {"message": "conflict private entity"}, AirDcppConflictError),
        (422, {"message": "invalid private entity"}, AirDcppConflictError),
        (429, {"message": "slow down private entity"}, AirDcppRateLimitError),
        (500, {"message": "server private entity"}, AirDcppUnavailableError),
    ],
)
async def test_http_errors_are_typed_and_do_not_leak_raw_values(
    status: int,
    body: dict[str, object],
    error_type: type[Exception],
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body, headers={"Retry-After": "12"})

    client = _client(handler)
    with pytest.raises(error_type) as raised:
        await client.authorize()
    await client.aclose()

    rendered = f"{raised.value!s} {raised.value!r}"
    assert "local-password" not in rendered
    assert "private entity" not in rendered
    if isinstance(raised.value, AirDcppPermissionError):
        assert raised.value.missing_permission == "queue_view"
    if isinstance(raised.value, AirDcppRateLimitError):
        assert raised.value.retry_after_seconds == 12


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b""),
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json={"session_id": 123}),
        httpx.Response(302, headers={"Location": "http://other.test/api/v1/"}),
    ],
)
async def test_invalid_responses_fail_closed_without_body_leak(
    response: httpx.Response,
) -> None:
    client = _client(lambda _request: response)
    with pytest.raises(AirDcppResponseError) as raised:
        await client.authorize()
    await client.aclose()

    assert "not-json" not in str(raised.value)
    assert "other.test" not in str(raised.value)


async def test_oversized_response_fails_before_json_parsing() -> None:
    client = _client(
        lambda _request: httpx.Response(200, content=b"x" * 65),
        max_response_bytes=64,
    )

    with pytest.raises(AirDcppResponseError, match="response exceeded"):
        await client.authorize()
    await client.aclose()


async def test_transport_timeout_is_normalized_without_endpoint_or_secret() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("private timeout detail", request=request)

    client = _client(handler)
    with pytest.raises(AirDcppUnavailableError) as raised:
        await client.authorize()
    await client.aclose()

    rendered = str(raised.value)
    assert "private timeout detail" not in rendered
    assert "local-password" not in rendered
    assert "airdcpp.test" not in rendered


def test_client_uses_explicit_timeouts_and_bounded_pool() -> None:
    client = _client(lambda _request: httpx.Response(204))

    assert client.timeout.connect == 15
    assert client.timeout.read == 15
    assert client.max_connections == 4
    assert client.max_keepalive_connections == 2
