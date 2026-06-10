"""Integration tests for system-wide health monitoring.

Tests cover the navigation health badge, external monitoring support
(response headers, HTTP status codes), HTMX partial rendering,
and end-to-end health check workflows.

Run:
    pytest tests/integration/test_health_integration.py -v
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if TYPE_CHECKING:
    from httpx import AsyncClient

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-health-integration")

pytest_plugins = ["conftest_security"]

HEALTH_URL = "/api/v1/health"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _persist_summary_rows(sec_db, statuses: list[str]) -> None:
    """Persist top-level health summary rows for API overview reads."""
    from pullbox.models.health import HealthCheckResult, HealthCurrentStatus, HealthStatus

    checked_at = datetime.now(UTC)
    async with sec_db() as session:
        for index, status in enumerate(statuses):
            component = f"component_{index}"
            check_name = f"check_{index}"
            health_status = HealthStatus(status)
            row_checked_at = checked_at + timedelta(seconds=index)
            session.add(
                HealthCheckResult(
                    component=component,
                    check_name=check_name,
                    status=health_status,
                    message=f"Message for {status}",
                    details_json=None,
                    response_time_ms=10.0 + index,
                    checked_at=row_checked_at,
                    is_summary=True,
                    run_id="run-1",
                )
            )
            session.add(
                HealthCurrentStatus(
                    component=component,
                    current_key="__summary__",
                    check_name=check_name,
                    subject_key=None,
                    subject_key_norm="",
                    status=health_status,
                    message=f"Message for {status}",
                    details_json=None,
                    response_time_ms=10.0 + index,
                    checked_at=row_checked_at,
                    is_summary=True,
                    run_id="run-1",
                )
            )
        await session.commit()


# ---------------------------------------------------------------------------
# Part A — Navigation Health Badge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestHealthBadge:
    """Tests for the /health/badge HTMX partial."""

    async def test_badge_slot_stays_invisible_when_all_healthy(
        self, authenticated_client: AsyncClient
    ) -> None:
        """All healthy -> invisible badge fragment with no count."""
        with patch(
            "pullbox.ui.routes.load_sidebar_health_counts",
            new_callable=AsyncMock,
            return_value=(0, 0),
        ):
            resp = await authenticated_client.get("/health/badge")
        assert resp.status_code == 200
        html = resp.text
        assert "opacity-0" in html
        assert 'data-sidebar-count="0"' in html
        assert "count-badge-error" not in html
        assert "count-badge-warning" not in html
        assert "no-store" in resp.headers["cache-control"]

    async def test_badge_shows_yellow_when_degraded(
        self, authenticated_client: AsyncClient
    ) -> None:
        """Any degraded -> yellow badge with count."""
        with patch(
            "pullbox.ui.routes.load_sidebar_health_counts",
            new_callable=AsyncMock,
            return_value=(1, 0),
        ):
            resp = await authenticated_client.get("/health/badge")
        assert resp.status_code == 200
        html = resp.text
        assert "count-badge-warning" in html
        # Count should be 1 (one degraded)
        assert ">1<" in html.replace(" ", "").replace("\n", "")

    async def test_badge_shows_red_when_unhealthy(self, authenticated_client: AsyncClient) -> None:
        """Any unhealthy -> red badge with count."""
        with patch(
            "pullbox.ui.routes.load_sidebar_health_counts",
            new_callable=AsyncMock,
            return_value=(1, 1),
        ):
            resp = await authenticated_client.get("/health/badge")
        assert resp.status_code == 200
        html = resp.text
        assert "count-badge-error" in html
        # Count should be 2 (1 unhealthy + 1 degraded)
        assert ">2<" in html.replace(" ", "").replace("\n", "")

    async def test_badge_count_matches_degraded_plus_unhealthy(
        self, authenticated_client: AsyncClient
    ) -> None:
        """Badge count = unhealthy + degraded components."""
        with patch(
            "pullbox.ui.routes.load_sidebar_health_counts",
            new_callable=AsyncMock,
            return_value=(1, 2),
        ):
            resp = await authenticated_client.get("/health/badge")
        html = resp.text
        assert ">3<" in html.replace(" ", "").replace("\n", "")

    async def test_badge_returns_html_fragment(self, authenticated_client: AsyncClient) -> None:
        """Badge endpoint returns an HTML fragment, not a full page."""
        with patch(
            "pullbox.ui.routes.load_sidebar_health_counts",
            new_callable=AsyncMock,
            return_value=(0, 0),
        ):
            resp = await authenticated_client.get("/health/badge")
        assert resp.status_code == 200
        html = resp.text
        # Should NOT contain full page structure
        assert "<!DOCTYPE" not in html
        assert "<html" not in html
        # Should contain a span element
        assert "<span" in html


# ---------------------------------------------------------------------------
# Part B — External Monitoring Support (Response Headers + Status Codes)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestExternalMonitoring:
    """Tests for external monitoring compatibility."""

    async def test_health_returns_x_health_status_header_healthy(
        self,
        authenticated_client: AsyncClient,
        sec_db,
    ) -> None:
        """X-Health-Status header reflects overall status."""
        await _persist_summary_rows(sec_db, ["healthy", "healthy"])
        resp = await authenticated_client.get(HEALTH_URL)
        assert resp.headers["x-health-status"] == "healthy"

    async def test_health_returns_x_health_status_header_unhealthy(
        self,
        authenticated_client: AsyncClient,
        sec_db,
    ) -> None:
        await _persist_summary_rows(sec_db, ["healthy", "unhealthy"])
        resp = await authenticated_client.get(HEALTH_URL)
        assert resp.headers["x-health-status"] == "unhealthy"

    async def test_health_returns_duration_header(
        self,
        authenticated_client: AsyncClient,
        sec_db,
    ) -> None:
        """X-Health-Check-Duration-Ms header is present and numeric."""
        await _persist_summary_rows(sec_db, ["healthy"])
        resp = await authenticated_client.get(HEALTH_URL)
        duration = resp.headers["x-health-check-duration-ms"]
        assert float(duration) >= 0

    async def test_http_200_for_healthy(
        self,
        authenticated_client: AsyncClient,
        sec_db,
    ) -> None:
        await _persist_summary_rows(sec_db, ["healthy", "healthy"])
        resp = await authenticated_client.get(HEALTH_URL)
        assert resp.status_code == 200

    async def test_http_200_for_degraded(
        self,
        authenticated_client: AsyncClient,
        sec_db,
    ) -> None:
        await _persist_summary_rows(sec_db, ["healthy", "degraded"])
        resp = await authenticated_client.get(HEALTH_URL)
        assert resp.status_code == 200

    async def test_http_503_for_unhealthy(
        self,
        authenticated_client: AsyncClient,
        sec_db,
    ) -> None:
        await _persist_summary_rows(sec_db, ["healthy", "unhealthy"])
        resp = await authenticated_client.get(HEALTH_URL)
        assert resp.status_code == 503

    async def test_health_json_parseable_for_uptime_kuma(
        self,
        authenticated_client: AsyncClient,
        sec_db,
    ) -> None:
        """Response is valid JSON with status field (Uptime Kuma expects this)."""
        await _persist_summary_rows(sec_db, ["healthy"])
        resp = await authenticated_client.get(HEALTH_URL)
        data = resp.json()
        assert "status" in data
        assert data["status"] in ("healthy", "degraded", "unhealthy", "unknown")
        assert "components" in data
        assert "timestamp" in data

    async def test_ping_endpoint_unauthenticated(self, unauthenticated_client: AsyncClient) -> None:
        """GET /ping works without auth (Docker HEALTHCHECK, Healthchecks.io)."""
        resp = await unauthenticated_client.get("/ping")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Part C — Provider Resilience
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestProviderResilience:
    """Tests for health check isolation — one provider failure doesn't break others."""

    async def test_health_check_survives_provider_timeout(
        self,
        authenticated_client: AsyncClient,
        sec_db,
    ) -> None:
        """If one component times out, other checks still return results."""
        await _persist_summary_rows(sec_db, ["healthy", "unhealthy", "healthy"])
        resp = await authenticated_client.get(HEALTH_URL)

        data = resp.json()
        # All 3 components should be present even though one is unhealthy
        assert len(data["components"]) == 3
        statuses = [c["status"] for c in data["components"]]
        assert "healthy" in statuses
        assert "unhealthy" in statuses

    async def test_full_workflow_consistency(
        self,
        authenticated_client: AsyncClient,
        sec_db,
    ) -> None:
        """Run checks -> API response matches expected structure and values."""
        await _persist_summary_rows(sec_db, ["healthy", "degraded", "unhealthy"])
        resp = await authenticated_client.get(HEALTH_URL)

        assert resp.status_code == 503
        data = resp.json()

        # Verify summary matches component list
        summary = data["summary"]
        assert summary["healthy"] == 1
        assert summary["degraded"] == 1
        assert summary["unhealthy"] == 1
        assert summary["total_check_time_ms"] > 0

        # Verify headers match body
        assert resp.headers["x-health-status"] == "unhealthy"
        duration = float(resp.headers["x-health-check-duration-ms"])
        assert duration == summary["total_check_time_ms"]
