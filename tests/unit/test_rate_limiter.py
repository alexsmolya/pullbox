"""Unit tests for core.rate_limiter — login rate limiting with per-IP tracking.

Tests cover attempt counting, lockout triggering, lockout expiry, window
expiry, cleanup, concurrent access, and IP isolation.

Run:
    pytest tests/unit/test_rate_limiter.py -v
    pytest tests/unit/test_rate_limiter.py -v --cov=pullbox.core.rate_limiter
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from pullbox.core.exceptions import LoginRateLimitError
from pullbox.core.rate_limiter import LoginRateLimiter

# ── Basic Behavior ─────────────────────────────────────────────────


class TestLoginRateLimiterBasics:
    """Tests for basic rate limiter counting and lockout behavior."""

    def test_default_thresholds_match_security_standard(self) -> None:
        limiter = LoginRateLimiter()

        assert limiter._max_attempts == 5
        assert limiter._window_seconds == 300.0
        assert limiter._lockout_seconds == 900.0

    @pytest.mark.asyncio
    async def test_allows_requests_under_limit(self) -> None:
        limiter = LoginRateLimiter(max_attempts=5)
        for _ in range(4):
            await limiter.record_failure("192.168.1.1")

        # 4 failures should NOT trigger lockout
        await limiter.check_rate_limit("192.168.1.1")

    @pytest.mark.asyncio
    async def test_blocks_after_max_attempts(self) -> None:
        limiter = LoginRateLimiter(max_attempts=5)
        for _ in range(5):
            await limiter.record_failure("192.168.1.1")

        with pytest.raises(LoginRateLimitError):
            await limiter.check_rate_limit("192.168.1.1")

    @pytest.mark.asyncio
    async def test_lockout_message_format(self) -> None:
        limiter = LoginRateLimiter(max_attempts=3, lockout_seconds=600.0)
        for _ in range(3):
            await limiter.record_failure("10.0.0.1")

        with pytest.raises(LoginRateLimitError, match=r"Try again in \d+ minutes"):
            await limiter.check_rate_limit("10.0.0.1")

    @pytest.mark.asyncio
    async def test_lockout_message_does_not_reveal_username(self) -> None:
        limiter = LoginRateLimiter(max_attempts=3)
        for _ in range(3):
            await limiter.record_failure("10.0.0.1")

        with pytest.raises(LoginRateLimitError) as exc_info:
            await limiter.check_rate_limit("10.0.0.1")

        msg = str(exc_info.value)
        assert "admin" not in msg.lower()
        assert "user" not in msg.lower()
        assert "Too many login attempts" in msg

    @pytest.mark.asyncio
    async def test_record_failure_creates_new_window(self) -> None:
        limiter = LoginRateLimiter(max_attempts=5)
        await limiter.record_failure("10.0.0.5")

        async with limiter._lock:
            record = limiter._records.get("10.0.0.5")
        assert record is not None
        assert record.count == 1
        assert record.locked_until is None


# ── Reset & Success ────────────────────────────────────────────────


class TestLoginRateLimiterResets:
    """Tests for counter reset on success and explicit admin reset."""

    @pytest.mark.asyncio
    async def test_success_resets_counter(self) -> None:
        limiter = LoginRateLimiter(max_attempts=5)
        for _ in range(4):
            await limiter.record_failure("192.168.1.1")

        await limiter.record_success("192.168.1.1")

        # Counter was cleared, so 4 more failures should NOT trigger lockout
        for _ in range(4):
            await limiter.record_failure("192.168.1.1")
        await limiter.check_rate_limit("192.168.1.1")

    @pytest.mark.asyncio
    async def test_reset_clears_entry(self) -> None:
        limiter = LoginRateLimiter(max_attempts=3)
        for _ in range(3):
            await limiter.record_failure("10.0.0.2")

        # Should be locked
        with pytest.raises(LoginRateLimitError):
            await limiter.check_rate_limit("10.0.0.2")

        # Admin resets
        await limiter.reset("10.0.0.2")

        # Should now be allowed
        await limiter.check_rate_limit("10.0.0.2")


# ── Expiry ─────────────────────────────────────────────────────────


class TestLoginRateLimiterExpiry:
    """Tests for natural expiry of windows and lockouts."""

    @pytest.mark.asyncio
    async def test_window_expires_naturally(self) -> None:
        limiter = LoginRateLimiter(max_attempts=5, window_seconds=0.1)
        for _ in range(4):
            await limiter.record_failure("10.0.0.3")

        await asyncio.sleep(0.15)

        # Window expired, so counter should reset — next failure starts fresh
        await limiter.record_failure("10.0.0.3")

        async with limiter._lock:
            record = limiter._records.get("10.0.0.3")
        assert record is not None
        assert record.count == 1

    @pytest.mark.asyncio
    async def test_lockout_expires_naturally(self) -> None:
        limiter = LoginRateLimiter(max_attempts=3, window_seconds=0.1, lockout_seconds=0.1)
        for _ in range(3):
            await limiter.record_failure("10.0.0.4")

        # Should be locked
        with pytest.raises(LoginRateLimitError):
            await limiter.check_rate_limit("10.0.0.4")

        await asyncio.sleep(0.15)

        # Lockout expired — access restored
        await limiter.check_rate_limit("10.0.0.4")


# ── Cleanup ────────────────────────────────────────────────────────


class TestLoginRateLimiterCleanup:
    """Tests for stale entry pruning."""

    @pytest.mark.asyncio
    async def test_cleanup_prunes_stale_entries(self) -> None:
        limiter = LoginRateLimiter(max_attempts=5, window_seconds=0.05, lockout_seconds=0.05)
        # Add some entries
        await limiter.record_failure("10.0.0.10")
        await limiter.record_failure("10.0.0.11")

        await asyncio.sleep(0.1)

        # Force cleanup by setting _last_cleanup far in the past
        with patch.object(limiter, "_last_cleanup", 0.0):
            async with limiter._lock:
                limiter._cleanup()

        async with limiter._lock:
            assert "10.0.0.10" not in limiter._records
            assert "10.0.0.11" not in limiter._records


# ── Concurrency & Isolation ────────────────────────────────────────


class TestLoginRateLimiterConcurrency:
    """Tests for concurrent access safety and IP isolation."""

    @pytest.mark.asyncio
    async def test_concurrent_access(self) -> None:
        limiter = LoginRateLimiter(max_attempts=100)

        async def hit() -> None:
            await limiter.record_failure("10.0.0.20")

        await asyncio.gather(*[hit() for _ in range(10)])

        async with limiter._lock:
            record = limiter._records.get("10.0.0.20")
        assert record is not None
        assert record.count == 10

    @pytest.mark.asyncio
    async def test_different_ips_tracked_independently(self) -> None:
        limiter = LoginRateLimiter(max_attempts=3)
        for _ in range(3):
            await limiter.record_failure("10.0.0.30")

        # IP-A is locked
        with pytest.raises(LoginRateLimitError):
            await limiter.check_rate_limit("10.0.0.30")

        # IP-B is NOT affected
        await limiter.check_rate_limit("10.0.0.31")
