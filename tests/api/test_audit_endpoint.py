"""Tests for the GET /api/v1/audit/events endpoint.

Run:
    pytest tests/api/test_audit_endpoint.py -v
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

import pytest

from pullbox.api.v1 import audit as audit_api
from pullbox.models.audit_log import AuditEventType, AuditLog

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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

    async def test_direct_handler_maps_events_and_total_pages(
        self,
        sec_db: async_sessionmaker[AsyncSession],
    ) -> None:
        """Direct handler coverage for non-empty event response serialization."""
        async with sec_db() as session:
            session.add_all(
                [
                    AuditLog(
                        event_type=AuditEventType.LOGIN_SUCCESS.value,
                        source_ip="127.0.0.1",
                        user_id=None,
                        username="admin",
                        detail="Logged in",
                    ),
                    AuditLog(
                        event_type=AuditEventType.LOGIN_SUCCESS.value,
                        source_ip="127.0.0.2",
                        user_id=None,
                        username="admin",
                        detail="Logged in again",
                    ),
                ]
            )
            await session.flush()

            result = await audit_api.list_audit_events(
                object(),  # type: ignore[arg-type]
                session,
                event_type=AuditEventType.LOGIN_SUCCESS.value,
                since=None,
                until=None,
                page=1,
                per_page=1,
            )

        assert result["total"] == 2
        assert result["page"] == 1
        assert result["total_pages"] == 2
        assert len(result["events"]) == 1
        assert result["events"][0]["event_type"] == AuditEventType.LOGIN_SUCCESS.value
