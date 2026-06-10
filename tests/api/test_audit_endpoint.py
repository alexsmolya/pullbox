"""Tests for the GET /api/v1/audit/events endpoint.

Run:
    pytest tests/api/test_audit_endpoint.py -v
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if TYPE_CHECKING:
    from httpx import AsyncClient

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-audit-tests")

pytest_plugins = ["conftest_security"]

AUDIT_URL = "/api/v1/audit/events"


@pytest.mark.asyncio
class TestAuditEndpoint:
    """Tests for the audit log API endpoint."""

    async def test_list_events_requires_auth(self, unauthenticated_client: AsyncClient) -> None:
        """Unauthenticated requests get 401."""
        resp = await unauthenticated_client.get(AUDIT_URL)
        assert resp.status_code == 401

    async def test_list_events_returns_events(self, authenticated_client: AsyncClient) -> None:
        """Authenticated request returns 200 with events array."""
        resp = await authenticated_client.get(AUDIT_URL)
        assert resp.status_code == 200
        data = resp.json()
        assert "events" in data
        assert "total" in data
        assert "page" in data
        assert "total_pages" in data
        assert isinstance(data["events"], list)

    async def test_list_events_filter_by_type(self, authenticated_client: AsyncClient) -> None:
        """Filtering by event_type returns only matching events."""
        resp = await authenticated_client.get(AUDIT_URL, params={"event_type": "login_success"})
        assert resp.status_code == 200
        data = resp.json()
        for event in data["events"]:
            assert event["event_type"] == "login_success"

    async def test_list_events_invalid_type_returns_all(
        self, authenticated_client: AsyncClient
    ) -> None:
        """Invalid event_type is treated as no filter."""
        resp = await authenticated_client.get(AUDIT_URL, params={"event_type": "nonexistent_type"})
        assert resp.status_code == 200

    async def test_list_events_pagination(self, authenticated_client: AsyncClient) -> None:
        """Pagination parameters work correctly."""
        resp = await authenticated_client.get(AUDIT_URL, params={"page": 1, "per_page": 10})
        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 1
        assert data["total_pages"] >= 1
