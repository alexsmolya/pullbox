"""Unit tests for the dashboard intelligence rollup task."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.exc import OperationalError

from pullbox.core.scheduler import get_registered_tasks
from pullbox.tasks.dashboard_task import refresh_dashboard_intelligence


class TestDashboardTask:
    """Verify the scheduled dashboard rollup task contract."""

    def test_dashboard_rollup_task_is_registered(self) -> None:
        """The dashboard intelligence task should be available to the scheduler."""
        registered_ids = {task.task_id for task in get_registered_tasks()}
        assert "refresh_dashboard_intelligence" in registered_ids

    @pytest.mark.asyncio
    async def test_refresh_dashboard_intelligence_captures_rollups(
        self,
        db_session,
    ) -> None:  # type: ignore[no-untyped-def]
        """The scheduled task should open a session and persist fresh rollups."""
        mock_service = AsyncMock()

        @asynccontextmanager
        async def mock_session_ctx():
            yield db_session

        with (
            patch("pullbox.tasks.dashboard_task.get_session_factory") as mock_factory,
            patch(
                "pullbox.tasks.dashboard_task.DashboardIntelligenceService",
                return_value=mock_service,
            ),
        ):
            mock_factory.return_value = mock_session_ctx

            await refresh_dashboard_intelligence()

        mock_service.capture_rollups.assert_awaited_once_with()
        assert db_session.in_transaction() is False

    @pytest.mark.asyncio
    async def test_refresh_dashboard_intelligence_retries_on_sqlite_lock(self) -> None:
        """The task should retry with a fresh session after a transient SQLite lock."""
        sessions = [AsyncMock(name="session_one"), AsyncMock(name="session_two")]
        services = [AsyncMock(name="service_one"), AsyncMock(name="service_two")]
        factory_calls = 0

        @asynccontextmanager
        async def mock_session_ctx():
            nonlocal factory_calls
            session = sessions[factory_calls]
            factory_calls += 1
            yield session

        sessions[0].commit.side_effect = OperationalError(
            "INSERT INTO dashboard_metric_rollups VALUES (...)",
            {},
            Exception("database is locked"),
        )
        sleep_spy = AsyncMock()
        with (
            patch("pullbox.tasks.dashboard_task.get_session_factory") as mock_factory,
            patch(
                "pullbox.tasks.dashboard_task.DashboardIntelligenceService",
                side_effect=services,
            ) as mock_service_cls,
            patch("pullbox.tasks.dashboard_task.asyncio.sleep", sleep_spy),
        ):
            mock_factory.return_value = mock_session_ctx

            await refresh_dashboard_intelligence()

        assert mock_service_cls.call_count == 2
        services[0].capture_rollups.assert_awaited_once_with()
        services[1].capture_rollups.assert_awaited_once_with()
        sessions[0].rollback.assert_awaited_once_with()
        sessions[1].commit.assert_awaited_once_with()
        sleep_spy.assert_awaited_once_with(0.25)
