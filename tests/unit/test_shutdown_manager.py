"""Tests for ShutdownManager — graceful restart via exit code 42.

Verifies:
- Not pending by default
- schedule_restart sets pending flag
- Exit code constant is 42
- _do_exit calls sys.exit(42)
- Multiple schedule calls are idempotent

Run:
    pytest tests/unit/test_shutdown_manager.py -v
"""

from __future__ import annotations

from unittest.mock import patch

from pullbox.core.shutdown import RESTART_EXIT_CODE, ShutdownManager


class TestShutdownManager:
    """ShutdownManager restart scheduling."""

    def test_not_pending_by_default(self) -> None:
        mgr = ShutdownManager()
        assert mgr.is_restart_pending is False

    def test_schedule_restart_sets_pending(self) -> None:
        mgr = ShutdownManager()
        with patch.object(mgr, "_do_exit"):
            mgr.schedule_restart()
        assert mgr.is_restart_pending is True

    def test_restart_exit_code(self) -> None:
        assert RESTART_EXIT_CODE == 42

    def test_do_exit_calls_sys_exit(self) -> None:
        mgr = ShutdownManager()
        with patch("pullbox.core.shutdown.sys.exit") as mock_exit:
            mgr._do_exit()
            mock_exit.assert_called_once_with(RESTART_EXIT_CODE)

    def test_multiple_schedule_calls_idempotent(self) -> None:
        mgr = ShutdownManager()
        call_count = 0

        def counting_exit() -> None:
            nonlocal call_count
            call_count += 1

        with patch.object(mgr, "_do_exit", side_effect=counting_exit):
            mgr.schedule_restart()
            mgr.schedule_restart()
            mgr.schedule_restart()
        assert mgr.is_restart_pending is True
        # _do_exit should only be scheduled once
        assert call_count <= 1
