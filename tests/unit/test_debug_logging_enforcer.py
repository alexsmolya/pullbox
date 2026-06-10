"""Unit tests for the app-level debug-logging expiry enforcer loop."""

from __future__ import annotations

import asyncio

import pytest


class TestDebugLoggingEnforcer:
    """The background expiry loop should poll and tolerate one-off failures."""

    @pytest.mark.asyncio
    async def test_enforcer_polls_once_before_cancellation(self, monkeypatch) -> None:
        from pullbox.app import _run_debug_logging_expiry_enforcer

        polled: list[str] = []

        async def _fake_poll() -> None:
            polled.append("tick")

        async def _cancel_sleep(_seconds: int) -> None:
            raise asyncio.CancelledError

        monkeypatch.setattr("pullbox.app._poll_debug_logging_expiry_once", _fake_poll)
        monkeypatch.setattr("pullbox.app.asyncio.sleep", _cancel_sleep)

        with pytest.raises(asyncio.CancelledError):
            await _run_debug_logging_expiry_enforcer()

        assert polled == ["tick"]

    @pytest.mark.asyncio
    async def test_enforcer_logs_failures_and_keeps_loop_alive(self, monkeypatch) -> None:
        from pullbox.app import _run_debug_logging_expiry_enforcer

        warning_events: list[str] = []

        async def _broken_poll() -> None:
            raise RuntimeError("boom")

        async def _cancel_sleep(_seconds: int) -> None:
            raise asyncio.CancelledError

        monkeypatch.setattr("pullbox.app._poll_debug_logging_expiry_once", _broken_poll)
        monkeypatch.setattr("pullbox.app.asyncio.sleep", _cancel_sleep)
        monkeypatch.setattr(
            "pullbox.app.logger.warning",
            lambda event, **_kwargs: warning_events.append(event),
        )

        with pytest.raises(asyncio.CancelledError):
            await _run_debug_logging_expiry_enforcer()

        assert "debug_logging_expiry_enforcer_failed" in warning_events
