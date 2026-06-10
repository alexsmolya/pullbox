"""Unit tests for core.api_rate_limiter — global tiered API rate limiting.

Tests cover tier classification, per-IP counting, limit enforcement,
window expiry, cleanup, concurrent access, and the disabled switch.

Run:
    pytest tests/unit/test_api_rate_limiter.py -v
    pytest tests/unit/test_api_rate_limiter.py -v --cov=pullbox.core.api_rate_limiter
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from pullbox.config import PullboxSettings
from pullbox.core.api_rate_limiter import APIRateLimiter, Tier
from pullbox.core.exceptions import PullboxError

# ── Tier Classification ────────────────────────────────────────────


class TestTierClassification:
    """Tests for endpoint tier classification logic."""

    def test_bootstrap_rate_limit_defaults_match_security_standard(self) -> None:
        fields = PullboxSettings.model_fields

        assert fields["rate_limit_enabled"].default is True
        assert fields["rate_limit_tier1"].default == 60
        assert fields["rate_limit_tier2"].default == 120
        assert fields["rate_limit_tier3"].default == 300

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/series/42/search",
            "/api/v1/series/1/refresh",
            "/api/v1/search/series",
            "/api/v1/search/releases",
            "/api/v1/search/library",
            "/api/v1/system/backup",
            "/api/v1/system/restore/backup-2026.db",
            "/api/v1/library/scan",
        ],
    )
    def test_tier_classification_expensive_paths(self, path: str) -> None:
        assert APIRateLimiter.classify(path, "POST") == Tier.TIER1

    @pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
    def test_tier_classification_write_methods(self, method: str) -> None:
        # A non-tier1 write path should be tier 2
        assert APIRateLimiter.classify("/api/v1/series", method) == Tier.TIER2

    def test_tier_classification_read_default(self) -> None:
        assert APIRateLimiter.classify("/api/v1/series", "GET") == Tier.TIER3
        assert APIRateLimiter.classify("/api/v1/issues/5", "GET") == Tier.TIER3

    @pytest.mark.parametrize(
        "path",
        ["/ping", "/health", "/static/js/app.js", "/covers/1/cover.jpg"],
    )
    def test_exempt_paths_classified(self, path: str) -> None:
        assert APIRateLimiter.classify(path, "GET") == Tier.EXEMPT

    def test_htmx_header_does_not_change_classification(self) -> None:
        """HTMX headers are treated like any other client-supplied header."""
        htmx_headers = {"hx-request": "true"}
        assert APIRateLimiter.classify("/api/v1/series", "GET", htmx_headers) == Tier.TIER3
        assert APIRateLimiter.classify("/api/v1/series", "POST", htmx_headers) == Tier.TIER2
        assert (
            APIRateLimiter.classify("/api/v1/series/42/search", "POST", htmx_headers) == Tier.TIER1
        )

    def test_non_htmx_requests_still_classified(self) -> None:
        """Requests without HX-Request header are classified normally."""
        assert APIRateLimiter.classify("/api/v1/series", "GET", {}) == Tier.TIER3
        assert APIRateLimiter.classify("/api/v1/series", "GET", None) == Tier.TIER3

    @pytest.mark.parametrize(
        "path",
        [
            "/",
            "/series",
            "/library",
            "/downloads",
            "/post-processing",
            "/import",
            "/import/orphaned",
            "/intervention",
            "/settings",
            "/security",
            "/health",
            "/system",
            "/setup",
            "/login",
        ],
    )
    def test_ui_routes_always_exempt(self, path: str) -> None:
        """UI page routes are never rate limited — only /api/ paths are."""
        assert APIRateLimiter.classify(path, "GET") == Tier.EXEMPT

    def test_ui_post_routes_exempt(self) -> None:
        """UI form submissions (POST to non-API routes) are also exempt."""
        assert APIRateLimiter.classify("/logout", "POST") == Tier.EXEMPT
        assert APIRateLimiter.classify("/login", "POST") == Tier.EXEMPT

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/series/1/cover",
            "/api/v1/series/42/cover",
            "/api/v1/series/999/cover",
            "/api/v1/issues/1/cover",
            "/api/v1/issues/42/cover",
        ],
    )
    def test_cover_image_routes_exempt(self, path: str) -> None:
        """Cover image API routes are exempt — high-volume read-only resources."""
        assert APIRateLimiter.classify(path, "GET") == Tier.EXEMPT


# ── Basic Rate Limiting ────────────────────────────────────────────


class TestAPIRateLimiterBasics:
    """Tests for basic counting and limit enforcement."""

    @pytest.mark.asyncio
    async def test_allows_requests_under_limit(self) -> None:
        limiter = APIRateLimiter(tier3=120)
        for _ in range(5):
            await limiter.check("10.0.0.1", "/api/v1/series", "GET")

    @pytest.mark.asyncio
    async def test_blocks_after_tier3_limit(self) -> None:
        limiter = APIRateLimiter(tier3=120)
        for _ in range(120):
            await limiter.check("10.0.0.1", "/api/v1/series", "GET")

        with pytest.raises(PullboxError) as exc_info:
            await limiter.check("10.0.0.1", "/api/v1/series", "GET")
        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_blocks_after_tier1_limit(self) -> None:
        limiter = APIRateLimiter(tier1=10)
        for _ in range(10):
            await limiter.check("10.0.0.1", "/api/v1/search/series", "GET")

        with pytest.raises(PullboxError) as exc_info:
            await limiter.check("10.0.0.1", "/api/v1/search/series", "GET")
        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_blocks_after_tier2_limit(self) -> None:
        limiter = APIRateLimiter(tier2=30)
        for _ in range(30):
            await limiter.check("10.0.0.1", "/api/v1/series", "POST")

        with pytest.raises(PullboxError) as exc_info:
            await limiter.check("10.0.0.1", "/api/v1/series", "POST")
        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_exempt_paths_never_blocked(self) -> None:
        limiter = APIRateLimiter(tier3=1)
        for _ in range(200):
            await limiter.check("10.0.0.1", "/ping", "GET")

    @pytest.mark.asyncio
    async def test_htmx_requests_are_rate_limited_normally(self) -> None:
        limiter = APIRateLimiter(tier3=1)
        htmx_headers = {"hx-request": "true"}
        await limiter.check("10.0.0.1", "/api/v1/series", "GET", headers=htmx_headers)
        with pytest.raises(PullboxError) as exc_info:
            await limiter.check("10.0.0.1", "/api/v1/series", "GET", headers=htmx_headers)
        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_different_ips_independent(self) -> None:
        limiter = APIRateLimiter(tier3=5)
        for _ in range(5):
            await limiter.check("10.0.0.1", "/api/v1/series", "GET")

        # IP-A is at limit
        with pytest.raises(PullboxError):
            await limiter.check("10.0.0.1", "/api/v1/series", "GET")

        # IP-B is unaffected
        await limiter.check("10.0.0.2", "/api/v1/series", "GET")


# ── Window Expiry ──────────────────────────────────────────────────


class TestAPIRateLimiterExpiry:
    """Tests for window reset after time passes."""

    @pytest.mark.asyncio
    async def test_window_resets_after_minute(self) -> None:
        limiter = APIRateLimiter(tier3=5)
        for _ in range(5):
            await limiter.check("10.0.0.1", "/api/v1/series", "GET")

        # Should be blocked
        with pytest.raises(PullboxError):
            await limiter.check("10.0.0.1", "/api/v1/series", "GET")

        # Advance the window_start to simulate 61 seconds ago
        async with limiter._lock:
            counter = limiter._counters["10.0.0.1"][Tier.TIER3]
            counter.window_start -= 61.0

        # Should now be allowed (new window starts)
        await limiter.check("10.0.0.1", "/api/v1/series", "GET")


# ── Headers & Metadata ─────────────────────────────────────────────


class TestAPIRateLimiterHeaders:
    """Tests for rate limit header helper methods."""

    @pytest.mark.asyncio
    async def test_returns_retry_after_header(self) -> None:
        limiter = APIRateLimiter(tier3=1)
        await limiter.check("10.0.0.1", "/api/v1/series", "GET")

        with pytest.raises(PullboxError) as exc_info:
            await limiter.check("10.0.0.1", "/api/v1/series", "GET")
        assert exc_info.value.code == "RATE_LIMITED"
        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_returns_rate_limit_headers(self) -> None:
        limiter = APIRateLimiter(tier3=120)
        await limiter.check("10.0.0.1", "/api/v1/series", "GET")

        limit = limiter.get_limit("/api/v1/series", "GET")
        remaining = limiter.get_remaining("10.0.0.1", "/api/v1/series", "GET")

        assert limit == 120
        assert remaining == 119

    @pytest.mark.asyncio
    async def test_get_remaining_for_unknown_ip(self) -> None:
        limiter = APIRateLimiter(tier3=120)
        remaining = limiter.get_remaining("10.0.0.99", "/api/v1/series", "GET")
        assert remaining == 120

    @pytest.mark.asyncio
    async def test_get_limit_for_exempt_path(self) -> None:
        limiter = APIRateLimiter()
        assert limiter.get_limit("/ping", "GET") == 0
        assert limiter.get_remaining("10.0.0.1", "/ping", "GET") == 0


# ── Disabled ───────────────────────────────────────────────────────


class TestAPIRateLimiterDisabled:
    """Tests for the master switch."""

    @pytest.mark.asyncio
    async def test_disabled_when_rate_limit_enabled_false(self) -> None:
        limiter = APIRateLimiter(tier3=1, enabled=False)
        # Even with limit=1, should never block when disabled
        for _ in range(100):
            await limiter.check("10.0.0.1", "/api/v1/series", "GET")


# ── Cleanup ────────────────────────────────────────────────────────


class TestAPIRateLimiterCleanup:
    """Tests for stale entry pruning."""

    @pytest.mark.asyncio
    async def test_cleanup_removes_stale_entries(self) -> None:
        limiter = APIRateLimiter(tier3=100)
        await limiter.check("10.0.0.1", "/api/v1/series", "GET")
        await limiter.check("10.0.0.2", "/api/v1/series", "GET")

        # Age the entries past the 60s window
        async with limiter._lock:
            for ip_counters in limiter._counters.values():
                for counter in ip_counters.values():
                    counter.window_start -= 120.0

        # Force cleanup by resetting last_cleanup time
        with patch.object(limiter, "_last_cleanup", 0.0):
            async with limiter._lock:
                limiter._cleanup()

        async with limiter._lock:
            assert "10.0.0.1" not in limiter._counters
            assert "10.0.0.2" not in limiter._counters


# ── Concurrency ────────────────────────────────────────────────────


class TestAPIRateLimiterConcurrency:
    """Tests for concurrent access safety."""

    @pytest.mark.asyncio
    async def test_concurrent_requests(self) -> None:
        limiter = APIRateLimiter(tier3=200)

        async def hit() -> None:
            await limiter.check("10.0.0.1", "/api/v1/series", "GET")

        await asyncio.gather(*[hit() for _ in range(50)])

        async with limiter._lock:
            counter = limiter._counters["10.0.0.1"][Tier.TIER3]
        assert counter.count == 50
