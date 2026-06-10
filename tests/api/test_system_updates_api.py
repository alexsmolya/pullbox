"""API tests for system update-check endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from pullbox.services.update_check import UpdateCheckResult, UpdateCheckService

if TYPE_CHECKING:
    from httpx import AsyncClient


@pytest.mark.asyncio
class TestSystemUpdateStatusApi:
    """Verify lazy caching and response contracts for update status."""

    async def test_requires_auth(self, unauthenticated_client: AsyncClient) -> None:
        resp = await unauthenticated_client.get("/api/v1/system/updates")
        assert resp.status_code == 401

    async def test_returns_cached_result_without_refreshing(
        self,
        authenticated_client: AsyncClient,
    ) -> None:
        service = UpdateCheckService()
        cached = UpdateCheckResult(
            current_version="1.2.3",
            latest_version="1.2.3",
            update_available=False,
            checked_at=datetime(2026, 5, 12, 12, 0, tzinfo=UTC),
        )

        with (
            patch.object(service, "get_cached", return_value=cached),
            patch.object(service, "check_for_update", new_callable=AsyncMock) as refresh,
            patch("pullbox.app.get_update_check_service", return_value=service),
        ):
            resp = await authenticated_client.get("/api/v1/system/updates")

        assert resp.status_code == 200
        assert resp.json()["checked"] is True
        assert resp.json()["current_version"] == "1.2.3"
        refresh.assert_not_awaited()

    async def test_lazy_checks_when_cache_is_empty(
        self,
        authenticated_client: AsyncClient,
    ) -> None:
        service = UpdateCheckService()
        fetched = UpdateCheckResult(
            current_version="1.2.3",
            latest_version="1.2.4",
            update_available=True,
            checked_at=datetime(2026, 5, 12, 12, 1, tzinfo=UTC),
            release_url="https://example.invalid/release",
            release_date="2026-05-12T00:00:00Z",
        )

        with (
            patch.object(service, "get_cached", return_value=None),
            patch.object(service, "check_for_update", AsyncMock(return_value=fetched)) as refresh,
            patch("pullbox.app.get_update_check_service", return_value=service),
        ):
            resp = await authenticated_client.get("/api/v1/system/updates")

        assert resp.status_code == 200
        data = resp.json()
        assert data["checked"] is True
        assert data["update_available"] is True
        assert data["latest_version"] == "1.2.4"
        refresh.assert_awaited_once_with()

    async def test_returns_unchecked_when_lazy_refresh_fails(
        self,
        authenticated_client: AsyncClient,
    ) -> None:
        service = UpdateCheckService()

        with (
            patch.object(service, "get_cached", return_value=None),
            patch.object(service, "check_for_update", AsyncMock(return_value=None)) as refresh,
            patch("pullbox.app.get_update_check_service", return_value=service),
        ):
            resp = await authenticated_client.get("/api/v1/system/updates")

        assert resp.status_code == 200
        assert resp.json() == {"checked": False}
        refresh.assert_awaited_once_with()
