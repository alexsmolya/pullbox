"""Login rate limiter — in-memory per-IP attempt tracking with sliding window lockout."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

import structlog

from pullbox.core.exceptions import LoginRateLimitError

logger = structlog.get_logger(__name__)

_CLEANUP_INTERVAL_SECONDS = 60.0


@dataclass
class _AttemptRecord:
    """Tracks login attempts for a single IP address."""

    count: int = 0
    window_start: float = field(default_factory=time.monotonic)
    locked_until: float | None = None


class LoginRateLimiter:
    """In-memory per-IP login attempt tracker with sliding window lockout.

    Configuration:
        max_attempts: Maximum failed attempts before lockout (default: 5)
        window_seconds: Time window for counting attempts (default: 300 = 5 min)
        lockout_seconds: Duration of lockout after exceeding max_attempts (default: 900 = 15 min)
    """

    def __init__(
        self,
        *,
        max_attempts: int = 5,
        window_seconds: float = 300.0,
        lockout_seconds: float = 900.0,
    ) -> None:
        self._max_attempts = max_attempts
        self._window_seconds = window_seconds
        self._lockout_seconds = lockout_seconds
        self._records: dict[str, _AttemptRecord] = {}
        self._lock = asyncio.Lock()
        self._last_cleanup: float = time.monotonic()

    async def check_rate_limit(self, ip: str) -> None:
        """Check whether an IP is currently locked out.

        Raises LoginRateLimitError if the IP has exceeded the failure threshold.
        """
        async with self._lock:
            self._cleanup()

            record = self._records.get(ip)
            if record is None:
                return

            now = time.monotonic()

            if record.locked_until is not None:
                if now < record.locked_until:
                    remaining_seconds = record.locked_until - now
                    retry_after_seconds = max(1, int(remaining_seconds + 0.999))
                    retry_after_minutes = max(1, int((remaining_seconds + 59.999) // 60))
                    raise LoginRateLimitError(
                        retry_after_seconds=retry_after_seconds,
                        message=(
                            f"Too many login attempts. Try again in {retry_after_minutes} minutes."
                        ),
                    )
                # Lockout expired — clear and allow through
                del self._records[ip]

    async def record_failure(self, ip: str) -> None:
        """Record a failed login attempt for an IP address."""
        async with self._lock:
            now = time.monotonic()
            record = self._records.get(ip)

            if record is None or (now - record.window_start) > self._window_seconds:
                # No record or window expired — start a new window
                self._records[ip] = _AttemptRecord(count=1, window_start=now)
                return

            record.count += 1

            if record.count >= self._max_attempts:
                record.locked_until = now + self._lockout_seconds
                logger.warning("login_rate_limit_lockout", ip=ip)

    async def record_success(self, ip: str) -> None:
        """Clear tracking for an IP after a successful login."""
        async with self._lock:
            self._records.pop(ip, None)

    async def reset(self, ip: str) -> None:
        """Admin-callable explicit reset for an IP address."""
        async with self._lock:
            self._records.pop(ip, None)

    def _cleanup(self) -> None:
        """Prune entries where both window and lockout have expired.

        Only runs at most once per _CLEANUP_INTERVAL_SECONDS.
        """
        now = time.monotonic()
        if (now - self._last_cleanup) < _CLEANUP_INTERVAL_SECONDS:
            return

        self._last_cleanup = now
        stale_ips: list[str] = []

        for ip, record in self._records.items():
            window_expired = (now - record.window_start) > self._window_seconds
            lockout_expired = record.locked_until is None or now >= record.locked_until

            if window_expired and lockout_expired:
                stale_ips.append(ip)

        for ip in stale_ips:
            del self._records[ip]

        if stale_ips:
            logger.debug("rate_limiter_cleanup", pruned_count=len(stale_ips))
