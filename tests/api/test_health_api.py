"""Tests for the health API endpoints.

Run:
    pytest tests/api/test_health_api.py -v
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pullbox.services.auth_service import SESSION_COOKIE_NAME, AuthService

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if TYPE_CHECKING:
    from pathlib import Path

    from httpx import AsyncClient

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-health-tests")

pytest_plugins = ["conftest_security"]

HEALTH_URL = "/api/v1/health"


def _csrf_header_for(client: AsyncClient) -> dict[str, str]:
    token = client.cookies.get(SESSION_COOKIE_NAME)
    csrf = AuthService.get_csrf_token_from_session(token) or ""
    return {"X-CSRF-Token": csrf}


def _mock_outcomes(
    statuses: list[str] | None = None,
) -> list[MagicMock]:
    """Build a list of mock CheckOutcome objects."""
    from pullbox.models.health import HealthStatus

    if statuses is None:
        statuses = ["healthy", "healthy", "healthy"]

    outcomes = []
    for i, status_str in enumerate(statuses):
        outcome = MagicMock()
        outcome.component = f"component_{i}"
        outcome.check_name = f"check_{i}"
        outcome.subject_key = None
        outcome.status = HealthStatus(status_str)
        outcome.message = f"Message for {status_str}"
        outcome.details = {}
        outcome.response_time_ms = 10.0 + i
        outcome.actionable_guidance = f"Fix {status_str}" if status_str != "healthy" else ""
        outcomes.append(outcome)
    return outcomes


@pytest.mark.asyncio
async def test_ping_is_unauthenticated_and_minimal(unauthenticated_client: AsyncClient) -> None:
    """Docker liveness probe must not expose internal health state."""
    resp = await unauthenticated_client.get("/ping")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "service": "pullbox"}


async def _persist_summary_rows(sec_db, rows: list[dict[str, object]]) -> None:
    """Persist summary rows that simulate completed health runs."""
    from pullbox.models.health import HealthCheckResult, HealthCurrentStatus, HealthStatus

    async with sec_db() as session:
        for row in rows:
            details = row.get("details")
            status = (
                row["status"]
                if isinstance(row["status"], HealthStatus)
                else HealthStatus(str(row["status"]))
            )
            checked_at = row.get("checked_at", datetime.now(UTC))
            component = str(row["component"])
            check_name = str(row.get("check_name", "connectivity"))
            message = str(row.get("message", ""))
            details_json = json.dumps(details) if details is not None else None
            response_time_ms = (
                None if row.get("response_time_ms") is None else float(row["response_time_ms"])
            )
            run_id = str(row.get("run_id", "run-1"))
            session.add(
                HealthCheckResult(
                    component=component,
                    check_name=check_name,
                    status=status,
                    message=message,
                    details_json=details_json,
                    response_time_ms=response_time_ms,
                    checked_at=checked_at,
                    is_summary=True,
                    run_id=run_id,
                )
            )
            session.add(
                HealthCurrentStatus(
                    component=component,
                    current_key="__summary__",
                    check_name=check_name,
                    subject_key=None,
                    subject_key_norm="",
                    status=status,
                    message=message,
                    details_json=details_json,
                    response_time_ms=response_time_ms,
                    checked_at=checked_at,
                    is_summary=True,
                    run_id=run_id,
                )
            )
        await session.commit()


@pytest.mark.asyncio
class TestHealthOverview:
    """Tests for GET /api/v1/health."""

    async def test_requires_auth(self, unauthenticated_client: AsyncClient) -> None:
        resp = await unauthenticated_client.get(HEALTH_URL)
        assert resp.status_code == 401

    async def test_returns_200_when_healthy(
        self,
        authenticated_client: AsyncClient,
        sec_db,
    ) -> None:
        now = datetime.now(UTC)
        await _persist_summary_rows(
            sec_db,
            [
                {
                    "component": "database",
                    "status": "healthy",
                    "message": "Connected",
                    "response_time_ms": 12.5,
                    "checked_at": now - timedelta(seconds=5),
                },
                {
                    "component": "filesystem",
                    "check_name": "accessibility",
                    "status": "healthy",
                    "message": "Writable",
                    "response_time_ms": 8.2,
                    "checked_at": now,
                },
            ],
        )

        resp = await authenticated_client.get(HEALTH_URL)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert "components" in data
        assert "summary" in data
        assert "timestamp" in data

    async def test_returns_503_when_unhealthy(
        self,
        authenticated_client: AsyncClient,
        sec_db,
    ) -> None:
        await _persist_summary_rows(
            sec_db,
            [
                {"component": "database", "status": "healthy", "message": "Connected"},
                {
                    "component": "system",
                    "check_name": "resources",
                    "status": "unhealthy",
                    "message": "Memory pressure critical",
                },
            ],
        )

        resp = await authenticated_client.get(HEALTH_URL)
        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "unhealthy"

    async def test_returns_200_when_degraded(
        self,
        authenticated_client: AsyncClient,
        sec_db,
    ) -> None:
        await _persist_summary_rows(
            sec_db,
            [
                {"component": "database", "status": "healthy", "message": "Connected"},
                {
                    "component": "indexers",
                    "status": "degraded",
                    "message": "2 services need attention",
                },
            ],
        )

        resp = await authenticated_client.get(HEALTH_URL)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded"

    async def test_summary_counts_are_correct(
        self,
        authenticated_client: AsyncClient,
        sec_db,
    ) -> None:
        await _persist_summary_rows(
            sec_db,
            [
                {"component": "database", "status": "healthy", "message": "Connected"},
                {"component": "filesystem", "status": "degraded", "message": "Low disk"},
                {"component": "system", "status": "unhealthy", "message": "Swap critical"},
                {"component": "comicvine", "status": "unknown", "message": "No recent data"},
            ],
        )

        resp = await authenticated_client.get(HEALTH_URL)
        data = resp.json()
        summary = data["summary"]
        assert summary["healthy"] == 1
        assert summary["degraded"] == 1
        assert summary["unhealthy"] == 1
        assert summary["unknown"] == 1
        total = summary["healthy"] + summary["degraded"] + summary["unhealthy"] + summary["unknown"]
        assert total == len(data["components"])

    async def test_response_schema_has_required_fields(
        self,
        authenticated_client: AsyncClient,
        sec_db,
    ) -> None:
        checked_at = datetime(2026, 4, 24, 19, 30, tzinfo=UTC)
        await _persist_summary_rows(
            sec_db,
            [
                {
                    "component": "database",
                    "status": "healthy",
                    "message": "Connected",
                    "response_time_ms": 7.5,
                    "checked_at": checked_at,
                }
            ],
        )

        resp = await authenticated_client.get(HEALTH_URL)
        data = resp.json()
        # Top-level fields
        assert "status" in data
        assert "timestamp" in data
        assert "components" in data
        assert "summary" in data
        assert data["timestamp"].startswith("2026-04-24T19:30:00")
        # Component fields
        comp = data["components"][0]
        assert "component" in comp
        assert "status" in comp
        assert "message" in comp
        assert "response_time_ms" in comp

    async def test_returns_unknown_without_persisted_results(
        self,
        authenticated_client: AsyncClient,
    ) -> None:
        resp = await authenticated_client.get(HEALTH_URL)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "unknown"
        assert data["components"] == []
        assert data["summary"] == {
            "healthy": 0,
            "degraded": 0,
            "unhealthy": 0,
            "unknown": 0,
            "total_check_time_ms": 0.0,
        }

    async def test_overview_reads_current_rows_without_history(
        self,
        authenticated_client: AsyncClient,
        sec_db,
    ) -> None:
        from pullbox.models.health import HealthCurrentStatus, HealthStatus

        checked_at = datetime(2026, 4, 24, 20, 0, tzinfo=UTC)
        async with sec_db() as session:
            session.add(
                HealthCurrentStatus(
                    component="database",
                    current_key="__summary__",
                    check_name="connectivity",
                    subject_key=None,
                    subject_key_norm="",
                    status=HealthStatus.HEALTHY,
                    message="Connected",
                    checked_at=checked_at,
                    is_summary=True,
                    run_id="run-current",
                )
            )
            await session.commit()

        resp = await authenticated_client.get(HEALTH_URL)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["components"][0]["component"] == "database"
        assert data["timestamp"].startswith("2026-04-24T20:00:00")


@pytest.mark.asyncio
class TestHealthComponent:
    """Tests for GET /api/v1/health/{component}."""

    async def test_returns_component_detail(
        self,
        authenticated_client: AsyncClient,
        sec_db,
    ) -> None:
        checked_at = datetime(2026, 4, 24, 19, 33, tzinfo=UTC)
        await _persist_summary_rows(
            sec_db,
            [
                {
                    "component": "database",
                    "status": "healthy",
                    "message": "Connected",
                    "checked_at": checked_at,
                    "details": {
                        "latency_ms": "0.6",
                        "checks": [
                            {
                                "check_name": "connection_round_trip",
                                "name": "Connection round trip",
                                "status": "healthy",
                                "message": "SELECT 1 completed in 0ms",
                                "response_time_ms": 0.3,
                            },
                            {
                                "check_name": "query_latency",
                                "name": "Query latency",
                                "status": "degraded",
                                "message": "Series registry read completed in 600ms",
                                "response_time_ms": 600.0,
                            },
                        ],
                    },
                }
            ],
        )

        resp = await authenticated_client.get(f"{HEALTH_URL}/database")
        assert resp.status_code == 200
        data = resp.json()
        assert data["component"] == "database"
        assert data["status"] == "healthy"
        assert len(data["checks"]) == 2
        assert data["checks"][0]["component"] == "database"
        assert data["checks"][0]["last_checked"].startswith("2026-04-24T19:33:00")
        assert data["checks"][1]["status"] == "degraded"
        assert data["checks"][1]["details"]["check_name"] == "query_latency"
        assert data["checks"][1]["details"]["name"] == "Query latency"

    async def test_returns_404_for_unknown_component(
        self, authenticated_client: AsyncClient
    ) -> None:
        resp = await authenticated_client.get(f"{HEALTH_URL}/nonexistent")
        assert resp.status_code == 404
        data = resp.json()
        assert "detail" in data

    async def test_returns_unknown_when_component_has_no_persisted_results(
        self,
        authenticated_client: AsyncClient,
    ) -> None:
        resp = await authenticated_client.get(f"{HEALTH_URL}/database")
        assert resp.status_code == 200
        data = resp.json()
        assert data["component"] == "database"
        assert data["status"] == "unknown"
        assert data["checks"] == []


@pytest.mark.asyncio
class TestHealthHistory:
    """Tests for GET /api/v1/health/{component}/history."""

    async def test_returns_history(self, authenticated_client: AsyncClient) -> None:
        from pullbox.models.health import HealthCheckResult, HealthStatus

        mock_row = MagicMock(spec=HealthCheckResult)
        mock_row.id = 1
        mock_row.component = "database"
        mock_row.check_name = "connectivity"
        mock_row.subject_key = None
        mock_row.subject_label = None
        mock_row.status = HealthStatus.HEALTHY
        mock_row.message = "OK"
        mock_row.details_json = '{"latency_ms": "5.0"}'
        mock_row.response_time_ms = 5.0
        mock_row.checked_at = "2026-03-02T12:00:00+00:00"

        with patch(
            "pullbox.api.v1.health.HealthService.get_history",
            new_callable=AsyncMock,
            return_value=[mock_row],
        ):
            resp = await authenticated_client.get(f"{HEALTH_URL}/database/history")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert len(data["items"]) == 1
        assert data["items"][0]["component"] == "database"

    async def test_history_returns_404_for_unknown_component(
        self, authenticated_client: AsyncClient
    ) -> None:
        resp = await authenticated_client.get(f"{HEALTH_URL}/nonexistent/history")
        assert resp.status_code == 404

    async def test_history_prefers_subcheck_rows_when_present(
        self,
        authenticated_client: AsyncClient,
        sec_db,
    ) -> None:
        from datetime import UTC, datetime

        from pullbox.models.health import HealthCheckResult, HealthStatus

        now = datetime.now(UTC)
        async with sec_db() as session:
            session.add_all(
                [
                    HealthCheckResult(
                        component="database",
                        check_name="connectivity",
                        status=HealthStatus.DEGRADED,
                        message="Database performance degraded",
                        details_json=None,
                        response_time_ms=600.0,
                        checked_at=now,
                        is_summary=True,
                        run_id="run-1",
                    ),
                    HealthCheckResult(
                        component="database",
                        check_name="query_latency",
                        status=HealthStatus.DEGRADED,
                        message="Series registry read took 600ms",
                        details_json=None,
                        response_time_ms=600.0,
                        checked_at=now,
                        is_summary=False,
                        run_id="run-1",
                    ),
                ]
            )
            await session.commit()

        resp = await authenticated_client.get(f"{HEALTH_URL}/database/history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["check_name"] == "query_latency"

    async def test_clear_history_deletes_component_rows(
        self,
        authenticated_client: AsyncClient,
        sec_db,
    ) -> None:
        from datetime import UTC, datetime

        from pullbox.models.health import HealthCheckResult, HealthStatus

        async with sec_db() as session:
            session.add_all(
                [
                    HealthCheckResult(
                        component="database",
                        check_name="connectivity",
                        status=HealthStatus.HEALTHY,
                        message="OK",
                        details_json=None,
                        response_time_ms=5.0,
                        checked_at=datetime.now(UTC),
                    ),
                    HealthCheckResult(
                        component="database",
                        check_name="query_latency",
                        status=HealthStatus.DEGRADED,
                        message="Slow query",
                        details_json=None,
                        response_time_ms=1250.0,
                        checked_at=datetime.now(UTC),
                    ),
                    HealthCheckResult(
                        component="filesystem",
                        check_name="writable",
                        status=HealthStatus.HEALTHY,
                        message="Writable",
                        details_json=None,
                        response_time_ms=8.0,
                        checked_at=datetime.now(UTC),
                    ),
                ]
            )
            await session.commit()

        resp = await authenticated_client.delete(
            f"{HEALTH_URL}/database/history",
            headers=_csrf_header_for(authenticated_client),
        )
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 2

        remaining = await authenticated_client.get(f"{HEALTH_URL}/database/history")
        assert remaining.status_code == 200
        assert remaining.json()["total"] == 0

        other_component = await authenticated_client.get(f"{HEALTH_URL}/filesystem/history")
        assert other_component.status_code == 200
        assert other_component.json()["total"] == 1


@pytest.mark.asyncio
class TestHealthIncidents:
    """Tests for GET /api/v1/health/incidents."""

    async def test_returns_compact_incidents(
        self,
        authenticated_client: AsyncClient,
        sec_db,
    ) -> None:
        from pullbox.models.health import HealthIncident, HealthStatus

        now = datetime(2026, 4, 24, 21, 0, tzinfo=UTC)
        async with sec_db() as session:
            session.add(
                HealthIncident(
                    component="indexers",
                    current_key="__summary__",
                    check_name="connectivity",
                    subject_key=None,
                    subject_key_norm="",
                    subject_label=None,
                    status=HealthStatus.UNHEALTHY,
                    is_summary=True,
                    first_seen_at=now - timedelta(minutes=10),
                    last_seen_at=now,
                    occurrence_count=3,
                    last_message="Prowlarr unreachable",
                    last_details_json='{"host": "prowlarr"}',
                    last_response_time_ms=0.0,
                    last_run_id="run-1",
                )
            )
            await session.commit()

        resp = await authenticated_client.get(f"{HEALTH_URL}/incidents")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["component"] == "indexers"
        assert data["items"][0]["status"] == "unhealthy"
        assert data["items"][0]["occurrence_count"] == 3
        assert data["items"][0]["details"] == {"host": "prowlarr"}

    async def test_filters_active_incidents(
        self,
        authenticated_client: AsyncClient,
        sec_db,
    ) -> None:
        from pullbox.models.health import HealthIncident, HealthStatus

        now = datetime(2026, 4, 24, 21, 0, tzinfo=UTC)
        async with sec_db() as session:
            session.add_all(
                [
                    HealthIncident(
                        component="database",
                        current_key="__summary__",
                        check_name="connectivity",
                        subject_key=None,
                        subject_key_norm="",
                        status=HealthStatus.UNHEALTHY,
                        is_summary=True,
                        first_seen_at=now - timedelta(minutes=10),
                        last_seen_at=now,
                        occurrence_count=1,
                        last_message="down",
                    ),
                    HealthIncident(
                        component="filesystem",
                        current_key="__summary__",
                        check_name="accessibility",
                        subject_key=None,
                        subject_key_norm="",
                        status=HealthStatus.DEGRADED,
                        is_summary=True,
                        first_seen_at=now - timedelta(hours=2),
                        last_seen_at=now - timedelta(hours=1),
                        resolved_at=now,
                        occurrence_count=2,
                        last_message="low disk",
                    ),
                ]
            )
            await session.commit()

        resp = await authenticated_client.get(f"{HEALTH_URL}/incidents?include_resolved=false")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["component"] == "database"


@pytest.mark.asyncio
class TestHealthRefresh:
    """Tests for POST /api/v1/health/refresh."""

    async def test_requires_auth(self, unauthenticated_client: AsyncClient) -> None:
        resp = await unauthenticated_client.post(f"{HEALTH_URL}/refresh")
        assert resp.status_code == 401

    async def test_triggers_check_run(self, authenticated_client: AsyncClient) -> None:
        outcomes = _mock_outcomes(["healthy", "healthy"])

        with patch(
            "pullbox.api.v1.health.run_health_refresh",
            new_callable=AsyncMock,
            return_value=outcomes,
        ) as run_health_refresh:
            resp = await authenticated_client.post(
                f"{HEALTH_URL}/refresh",
                headers=_csrf_header_for(authenticated_client),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["message"] == "Health checks completed"
        assert data["healthy"] == 2
        assert data["total_checks"] == 2
        run_health_refresh.assert_awaited_once_with()

    async def test_tolerates_registry_build_failures(
        self, authenticated_client: AsyncClient
    ) -> None:
        outcomes = _mock_outcomes(["healthy", "degraded"])

        with patch(
            "pullbox.api.v1.health.run_health_refresh",
            new_callable=AsyncMock,
            return_value=outcomes,
        ) as run_health_refresh:
            resp = await authenticated_client.post(
                f"{HEALTH_URL}/refresh",
                headers=_csrf_header_for(authenticated_client),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["message"] == "Health checks completed"
        assert data["healthy"] == 1
        assert data["degraded"] == 1
        assert data["total_checks"] == 2
        run_health_refresh.assert_awaited_once_with()

    async def test_component_refresh_triggers_single_component_run(
        self, authenticated_client: AsyncClient
    ) -> None:
        outcomes = _mock_outcomes(["healthy", "degraded"])

        with patch(
            "pullbox.api.v1.health.run_health_refresh",
            new_callable=AsyncMock,
            return_value=outcomes,
        ) as run_health_refresh:
            resp = await authenticated_client.post(
                f"{HEALTH_URL}/database/refresh",
                headers=_csrf_header_for(authenticated_client),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["message"] == "Health component check completed"
        assert data["component"] == "database"
        assert data["healthy"] == 1
        assert data["degraded"] == 1
        assert data["total_checks"] == 2
        run_health_refresh.assert_awaited_once_with(component="database")

    async def test_component_refresh_rejects_unknown_component(
        self, authenticated_client: AsyncClient
    ) -> None:
        resp = await authenticated_client.post(
            f"{HEALTH_URL}/definitely_not_real/refresh",
            headers=_csrf_header_for(authenticated_client),
        )

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Unknown component: definitely_not_real"

    async def test_database_optimize_runs_maintenance_and_refreshes_health(
        self,
        authenticated_client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        class FakeResult:
            reclaimed_bytes = 4096
            before = type(
                "Before",
                (),
                {
                    "database_bytes": 8192,
                    "wal_bytes": 1024,
                    "free_pages": 1,
                    "reclaimable_bytes": 4096,
                },
            )()
            after = type(
                "After",
                (),
                {
                    "database_bytes": 4096,
                    "wal_bytes": 0,
                    "free_pages": 0,
                    "reclaimable_bytes": 0,
                },
            )()

        runtime = MagicMock()
        runtime.optimize = AsyncMock(return_value=FakeResult())
        refresh = AsyncMock(return_value=[])
        monkeypatch.setattr(
            "pullbox.api.v1.health._sqlite_database_path",
            lambda _session: tmp_path / "pullbox.db",
        )
        monkeypatch.setattr(
            "pullbox.api.v1.health.DatabaseOptimizationRuntimeService",
            lambda _path: runtime,
        )
        monkeypatch.setattr("pullbox.api.v1.health.run_health_refresh", refresh)

        response = await authenticated_client.post(
            f"{HEALTH_URL}/database/optimize",
            headers=_csrf_header_for(authenticated_client),
        )

        assert response.status_code == 200
        assert response.json()["reclaimed_bytes"] == 4096
        runtime.optimize.assert_awaited_once_with()
        refresh.assert_awaited_once_with(component="database")

    async def test_database_optimize_rejects_active_import(
        self,
        authenticated_client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        from pullbox.core.exceptions import ValidationError

        async def reject_active_import(_session: object) -> None:
            raise ValidationError(
                "Database optimization is unavailable while an import or rollback is active."
            )

        monkeypatch.setattr(
            "pullbox.api.v1.health._ensure_database_optimization_is_admissible",
            reject_active_import,
        )
        monkeypatch.setattr(
            "pullbox.api.v1.health._sqlite_database_path",
            lambda _session: tmp_path / "pullbox.db",
        )

        response = await authenticated_client.post(
            f"{HEALTH_URL}/database/optimize",
            headers=_csrf_header_for(authenticated_client),
        )

        assert response.status_code == 422
        assert "import or rollback" in response.json()["error"]["message"]


@pytest.mark.asyncio
class TestSystemStatus:
    """Tests for GET /api/v1/system/status."""

    async def test_requires_auth(self, unauthenticated_client: AsyncClient) -> None:
        resp = await unauthenticated_client.get("/api/v1/system/status")
        assert resp.status_code == 401

    async def test_returns_system_info(self, authenticated_client: AsyncClient) -> None:
        resp = await authenticated_client.get("/api/v1/system/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "version" in data
        assert "python_version" in data
        assert "platform" in data
        assert "uptime_seconds" in data
        assert "started_at" in data


@pytest.mark.asyncio
class TestHealthHistoryEdgeCases:
    """Edge-case tests for history endpoint."""

    async def test_history_handles_invalid_json_in_details(
        self, authenticated_client: AsyncClient
    ) -> None:
        """details_json with invalid JSON should be returned as None."""
        mock_row = MagicMock()
        mock_row.id = 1
        mock_row.component = "database"
        mock_row.check_name = "connectivity"
        mock_row.subject_key = None
        mock_row.subject_label = None
        mock_row.status = "healthy"
        mock_row.message = "OK"
        mock_row.details_json = "NOT VALID JSON {{"
        mock_row.response_time_ms = 5.0
        mock_row.checked_at = "2026-03-02T12:00:00+00:00"

        with patch(
            "pullbox.api.v1.health.HealthService.get_history",
            new_callable=AsyncMock,
            return_value=[mock_row],
        ):
            resp = await authenticated_client.get(f"{HEALTH_URL}/database/history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"][0]["details"] is None
