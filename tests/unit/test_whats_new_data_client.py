"""Tests for the pullbox-data release client used by What's New."""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx
import pytest

from pullbox import __version__
from pullbox.config import get_settings
from pullbox.services.whats_new_data_client import (
    PullboxDataClientError,
    WhatsNewDataClient,
)


def _json_response(status_code: int, payload: dict[str, Any]) -> httpx.Response:
    return httpx.Response(status_code, json=payload)


class TestWhatsNewDataClient:
    async def test_current_week_uses_configured_base_url_and_store_date(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PULLBOX_DATA_API_BASE_URL", "https://data.example.test/root/")
        get_settings.cache_clear()
        seen_requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            seen_requests.append(request)
            return _json_response(200, {"count": 0, "issues": []})

        client = WhatsNewDataClient(transport=httpx.MockTransport(handler))

        response = await client.get_current_week(date(2026, 5, 13))

        assert response == {"count": 0, "issues": []}
        assert len(seen_requests) == 1
        request = seen_requests[0]
        assert (
            str(request.url)
            == "https://data.example.test/root/api/v1/releases?store_date=2026-05-13"
        )
        assert request.headers["user-agent"] == f"Pullbox/{__version__}"

    async def test_current_week_without_store_date_uses_default_upstream_week(self) -> None:
        seen_requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            seen_requests.append(request)
            return _json_response(200, {"store_date": "2026-05-13", "count": 0, "issues": []})

        client = WhatsNewDataClient(
            base_url="https://api.example.test",
            transport=httpx.MockTransport(handler),
        )

        response = await client.get_current_week()

        assert response == {"store_date": "2026-05-13", "count": 0, "issues": []}
        assert str(seen_requests[0].url) == "https://api.example.test/api/v1/releases"

    async def test_upcoming_includes_upcoming_flag_and_optional_publisher(self) -> None:
        seen_requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            seen_requests.append(request)
            return _json_response(200, {"weeks": [], "lookahead_weeks": 8})

        client = WhatsNewDataClient(
            base_url="https://api.example.test",
            transport=httpx.MockTransport(handler),
        )

        response = await client.get_upcoming(publisher="DC Comics")

        assert response == {"weeks": [], "lookahead_weeks": 8}
        assert len(seen_requests) == 1
        assert (
            str(seen_requests[0].url)
            == "https://api.example.test/api/v1/releases?upcoming=true&publisher=DC+Comics"
        )

    async def test_retries_retryable_server_failures(self) -> None:
        statuses = [503, 200]
        seen_requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            seen_requests.append(request)
            return _json_response(statuses.pop(0), {"ok": True})

        client = WhatsNewDataClient(
            base_url="https://api.example.test",
            transport=httpx.MockTransport(handler),
            retry_backoff_seconds=0,
        )

        response = await client.get_current_week(date(2026, 5, 13))

        assert response == {"ok": True}
        assert len(seen_requests) == 2

    async def test_does_not_retry_client_errors(self) -> None:
        seen_requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            seen_requests.append(request)
            return _json_response(404, {"detail": "not found"})

        client = WhatsNewDataClient(
            base_url="https://api.example.test",
            transport=httpx.MockTransport(handler),
            retry_backoff_seconds=0,
        )

        with pytest.raises(PullboxDataClientError) as exc_info:
            await client.get_current_week(date(2026, 5, 13))

        assert exc_info.value.status_code == 404
        assert len(seen_requests) == 1

    async def test_retries_transport_timeouts_then_raises(self) -> None:
        attempts = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            raise httpx.ReadTimeout("timed out", request=request)

        client = WhatsNewDataClient(
            base_url="https://api.example.test",
            transport=httpx.MockTransport(handler),
            retry_backoff_seconds=0,
        )

        with pytest.raises(PullboxDataClientError) as exc_info:
            await client.get_upcoming()

        assert exc_info.value.status_code is None
        assert attempts == 3

    async def test_test_connection_returns_status_payload(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert str(request.url) == "https://api.example.test/api/v1/releases"
            return _json_response(200, {"count": 7, "issues": []})

        client = WhatsNewDataClient(
            base_url="https://api.example.test",
            transport=httpx.MockTransport(handler),
        )

        assert await client.test_connection() == {
            "ok": True,
            "status_code": 200,
            "reachable": True,
        }
