"""Graceful shutdown manager — handles restart requests via exit code 42."""

from __future__ import annotations

import sys
import threading

import structlog

logger = structlog.get_logger(__name__)

RESTART_EXIT_CODE = 42
_RESTART_DELAY_SECONDS = 1.0


class ShutdownManager:
    """Manages graceful restart requests.

    When schedule_restart() is called, the process exits with code 42
    after a brief delay. Wrapper scripts (Docker entrypoint, systemd,
    direct-install script) detect this exit code and relaunch the app.
    """

    def __init__(self) -> None:
        self._restart_pending: bool = False

    @property
    def is_restart_pending(self) -> bool:
        """Whether a restart has been scheduled."""
        return self._restart_pending

    def schedule_restart(self) -> None:
        """Schedule a process exit with code 42 after a brief delay."""
        if self._restart_pending:
            return
        self._restart_pending = True
        logger.info("restart_scheduled", exit_code=RESTART_EXIT_CODE)
        timer = threading.Timer(_RESTART_DELAY_SECONDS, self._do_exit)
        timer.daemon = True
        timer.start()

    def _do_exit(self) -> None:
        """Execute the exit. Separated for testability."""
        logger.info("restart_executing", exit_code=RESTART_EXIT_CODE)
        sys.exit(RESTART_EXIT_CODE)


# Module-level singleton
shutdown_manager = ShutdownManager()
