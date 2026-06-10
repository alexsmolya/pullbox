"""Global API rate limiter — tiered per-IP request throttling.

Provides three tiers of rate limiting based on endpoint cost:
- Tier 1 (expensive): External API calls, backups, scans — 60/min
- Tier 2 (write): State-changing POST/PUT/PATCH/DELETE — 120/min
- Tier 3 (read): GET requests — 300/min

Exempt paths (/ping, /health, /static/*) bypass all rate limiting.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

import structlog

from pullbox.core.exceptions import PullboxError

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = structlog.get_logger(__name__)

_CLEANUP_INTERVAL_SECONDS = 60.0
_WINDOW_SECONDS = 60.0

# Paths that trigger external API calls or heavy I/O
_TIER1_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^/api/v1/series/\d+/search$"),
    re.compile(r"^/api/v1/series/\d+/refresh$"),
    re.compile(r"^/api/v1/search/"),
    re.compile(r"^/api/v1/system/backup$"),
    re.compile(r"^/api/v1/system/restore/"),
    re.compile(r"^/api/v1/library/scan$"),
]

_EXEMPT_PREFIXES = ("/ping", "/health", "/static/", "/covers/")

# Patterns within /api/ that are exempt — high-volume read-only resources
_EXEMPT_API_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^/api/v1/series/\d+/cover$"),
    re.compile(r"^/api/v1/issues/\d+/cover$"),
]

# Only rate-limit API endpoints — UI page navigation is behind session
# auth and should never be throttled.
_RATE_LIMITED_PREFIXES = ("/api/",)

_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class Tier(StrEnum):
    """Rate limit tier classification."""

    TIER1 = "tier1"
    TIER2 = "tier2"
    TIER3 = "tier3"
    EXEMPT = "exempt"


@dataclass
class _WindowCounter:
    """Tracks request count within a sliding time window."""

    count: int = 0
    window_start: float = field(default_factory=time.monotonic)


class APIRateLimiter:
    """Global per-IP API rate limiter using a sliding window counter.

    Tracks request counts per IP in configurable time windows with
    different limits for different endpoint tiers.
    """

    def __init__(
        self,
        *,
        tier1: int = 10,
        tier2: int = 30,
        tier3: int = 120,
        enabled: bool = True,
    ) -> None:
        self._limits: dict[str, int] = {
            Tier.TIER1: tier1,
            Tier.TIER2: tier2,
            Tier.TIER3: tier3,
        }
        self.enabled = enabled
        # IP → tier → counter
        self._counters: dict[str, dict[str, _WindowCounter]] = {}
        self._lock = asyncio.Lock()
        self._last_cleanup: float = time.monotonic()

    @staticmethod
    def classify(path: str, method: str, headers: Mapping[str, str] | None = None) -> Tier:
        """Determine the rate limit tier for a request."""
        # Only rate-limit API endpoints; everything else is exempt
        if not any(path.startswith(prefix) for prefix in _RATE_LIMITED_PREFIXES):
            return Tier.EXEMPT

        if any(path.startswith(prefix) for prefix in _EXEMPT_PREFIXES):
            return Tier.EXEMPT

        # Exempt high-volume API resources (cover images)
        if any(pattern.match(path) for pattern in _EXEMPT_API_PATTERNS):
            return Tier.EXEMPT

        # Tier 1: expensive operations (check path patterns)
        for pattern in _TIER1_PATTERNS:
            if pattern.match(path):
                return Tier.TIER1

        # Tier 2: write operations
        if method in _WRITE_METHODS:
            return Tier.TIER2

        # Tier 3: read operations (default)
        return Tier.TIER3

    async def check(
        self,
        ip: str,
        path: str,
        method: str,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        """Check and increment the rate limit counter for a request.

        Raises PullboxError with status 429 if the limit is exceeded.
        """
        if not self.enabled:
            return

        tier = self.classify(path, method, headers)
        if tier == Tier.EXEMPT:
            return

        async with self._lock:
            self._cleanup()

            now = time.monotonic()
            ip_counters = self._counters.setdefault(ip, {})
            counter = ip_counters.get(tier)

            if counter is None or (now - counter.window_start) >= _WINDOW_SECONDS:
                # Start a new window
                ip_counters[tier] = _WindowCounter(count=1, window_start=now)
                return

            if counter.count >= self._limits[tier]:
                logger.warning(
                    "api_rate_limit_exceeded",
                    ip=ip,
                    tier=tier,
                    path=path,
                    limit=self._limits[tier],
                )
                raise PullboxError(
                    message="Rate limit exceeded. Try again in 60 seconds.",
                    code="RATE_LIMITED",
                    status_code=429,
                )

            counter.count += 1

    def get_remaining(
        self, ip: str, path: str, method: str, headers: Mapping[str, str] | None = None
    ) -> int:
        """Return the number of requests remaining in the current window."""
        tier = self.classify(path, method, headers)
        if tier == Tier.EXEMPT:
            return 0

        limit = self._limits[tier]
        ip_counters = self._counters.get(ip)
        if ip_counters is None:
            return limit

        counter = ip_counters.get(tier)
        if counter is None:
            return limit

        now = time.monotonic()
        if (now - counter.window_start) >= _WINDOW_SECONDS:
            return limit

        return max(0, limit - counter.count)

    def get_limit(self, path: str, method: str, headers: Mapping[str, str] | None = None) -> int:
        """Return the rate limit for a given path and method."""
        tier = self.classify(path, method, headers)
        if tier == Tier.EXEMPT:
            return 0
        return self._limits[tier]

    def _cleanup(self) -> None:
        """Prune stale window counters.

        Only runs at most once per _CLEANUP_INTERVAL_SECONDS.
        """
        now = time.monotonic()
        if (now - self._last_cleanup) < _CLEANUP_INTERVAL_SECONDS:
            return

        self._last_cleanup = now
        stale_ips: list[str] = []

        for ip, tiers in self._counters.items():
            stale_tiers = [
                tier
                for tier, counter in tiers.items()
                if (now - counter.window_start) >= _WINDOW_SECONDS
            ]
            for tier in stale_tiers:
                del tiers[tier]
            if not tiers:
                stale_ips.append(ip)

        for ip in stale_ips:
            del self._counters[ip]

        if stale_ips:
            logger.debug("api_rate_limiter_cleanup", pruned_ips=len(stale_ips))
