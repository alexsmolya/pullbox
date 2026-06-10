"""Shared helpers for transient SQLite write-lock retries."""

from __future__ import annotations

SQLITE_LOCK_RETRY_ATTEMPTS = 8
SQLITE_LOCK_RETRY_BASE_DELAY_SECONDS = 0.25


def is_sqlite_locked_error(exc: BaseException) -> bool:
    """Return whether an operational error is SQLite write-lock contention."""
    message = str(exc).lower()
    return "database is locked" in message or "locking protocol" in message


def sqlite_lock_retry_delay(attempt: int) -> float:
    """Return the linear backoff delay for a SQLite lock retry attempt."""
    return SQLITE_LOCK_RETRY_BASE_DELAY_SECONDS * attempt
