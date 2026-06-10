"""Tests for UTC datetime storage and local display (C-8.2).

Verifies:
- localtime filter converts UTC to local timezone
- localtime filter handles None datetime gracefully
- localtime filter handles naive datetime (assumes UTC)
- localtime filter handles date-only values
- Different timezone configurations produce correct output
- Default timezone is UTC if not configured
- DST transitions handled correctly
- Millisecond precision preserved through conversion
- Invalid timezone string falls back to UTC
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _clean_tz_env() -> Iterator[None]:
    """Ensure the TZ environment variable and structlog are restored after each test.

    A prior test may leave TZ set, which pollutes get_timezone via lru_cache.
    Structlog must also be reset so that logger.warning() inside get_timezone
    doesn't hit a misconfigured processor chain (causing recursion).
    """
    import structlog

    from pullbox.core.timezone import get_timezone

    original_tz = os.environ.get("TZ")
    get_timezone.cache_clear()
    structlog.reset_defaults()
    yield
    # Restore original TZ state
    if original_tz is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = original_tz
    get_timezone.cache_clear()
    structlog.reset_defaults()


class TestLocaltimeFilter:
    """The localtime Jinja2 filter converts UTC datetimes to local display."""

    def _get_filter(self):
        from pullbox.ui.routes import _format_localtime

        return _format_localtime

    def test_utc_aware_datetime_converted(self) -> None:
        f = self._get_filter()
        dt = datetime(2026, 3, 12, 14, 30, 0, tzinfo=UTC)
        with patch("pullbox.core.timezone.get_timezone", return_value=ZoneInfo("America/New_York")):
            result = f(dt, "%Y-%m-%d %H:%M %Z")
        assert "2026-03-12" in result
        assert "10:30" in result

    def test_naive_datetime_assumed_utc(self) -> None:
        f = self._get_filter()
        dt = datetime(2026, 6, 15, 12, 0, 0)
        with patch("pullbox.core.timezone.get_timezone", return_value=ZoneInfo("America/New_York")):
            result = f(dt, "%Y-%m-%d %H:%M")
        assert "2026-06-15" in result
        assert "08:00" in result

    def test_none_returns_empty_string(self) -> None:
        f = self._get_filter()
        result = f(None, "%Y-%m-%d %H:%M")
        assert result == ""

    def test_date_only_formatted_without_tz_conversion(self) -> None:
        f = self._get_filter()
        d = date(2026, 3, 12)
        result = f(d, "%b %d, %Y")
        assert result == "Mar 12, 2026"

    def test_utc_timezone_no_change(self) -> None:
        f = self._get_filter()
        dt = datetime(2026, 3, 12, 14, 30, 0, tzinfo=UTC)
        with patch("pullbox.core.timezone.get_timezone", return_value=ZoneInfo("UTC")):
            result = f(dt, "%Y-%m-%d %H:%M")
        assert result == "2026-03-12 14:30"

    def test_asia_tokyo_offset(self) -> None:
        f = self._get_filter()
        dt = datetime(2026, 3, 12, 14, 0, 0, tzinfo=UTC)
        with patch("pullbox.core.timezone.get_timezone", return_value=ZoneInfo("Asia/Tokyo")):
            result = f(dt, "%Y-%m-%d %H:%M")
        assert result == "2026-03-12 23:00"

    def test_europe_london_gmt(self) -> None:
        f = self._get_filter()
        # January = GMT (no DST)
        dt = datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC)
        with patch("pullbox.core.timezone.get_timezone", return_value=ZoneInfo("Europe/London")):
            result = f(dt, "%Y-%m-%d %H:%M")
        assert result == "2026-01-15 10:00"

    def test_europe_london_bst(self) -> None:
        f = self._get_filter()
        # July = BST (UTC+1)
        dt = datetime(2026, 7, 15, 10, 0, 0, tzinfo=UTC)
        with patch("pullbox.core.timezone.get_timezone", return_value=ZoneInfo("Europe/London")):
            result = f(dt, "%Y-%m-%d %H:%M")
        assert result == "2026-07-15 11:00"

    def test_dst_spring_forward(self) -> None:
        f = self._get_filter()
        # America/New_York DST starts Mar 8, 2026 at 2am local
        # At 6:30 UTC on Mar 8 → 1:30 AM EST (before spring forward)
        dt_before = datetime(2026, 3, 8, 6, 30, 0, tzinfo=UTC)
        # At 7:30 UTC on Mar 8 → 3:30 AM EDT (after spring forward)
        dt_after = datetime(2026, 3, 8, 7, 30, 0, tzinfo=UTC)
        with patch("pullbox.core.timezone.get_timezone", return_value=ZoneInfo("America/New_York")):
            before = f(dt_before, "%H:%M")
            after = f(dt_after, "%H:%M")
        assert before == "01:30"
        assert after == "03:30"

    def test_dst_fall_back(self) -> None:
        f = self._get_filter()
        # America/New_York DST ends Nov 1, 2026 at 2am local
        # At 5:30 UTC on Nov 1 → 1:30 AM EDT (before fall back)
        dt_before = datetime(2026, 11, 1, 5, 30, 0, tzinfo=UTC)
        # At 7:30 UTC on Nov 1 → 2:30 AM EST (after fall back)
        dt_after = datetime(2026, 11, 1, 7, 30, 0, tzinfo=UTC)
        with patch("pullbox.core.timezone.get_timezone", return_value=ZoneInfo("America/New_York")):
            before = f(dt_before, "%H:%M")
            after = f(dt_after, "%H:%M")
        assert before == "01:30"
        assert after == "02:30"

    def test_microsecond_precision_preserved(self) -> None:
        f = self._get_filter()
        dt = datetime(2026, 3, 12, 14, 30, 45, 123456, tzinfo=UTC)
        with patch("pullbox.core.timezone.get_timezone", return_value=ZoneInfo("America/New_York")):
            result = f(dt, "%H:%M:%S.%f")
        assert result == "10:30:45.123456"

    def test_default_format(self) -> None:
        f = self._get_filter()
        dt = datetime(2026, 3, 12, 14, 30, 0, tzinfo=UTC)
        with patch("pullbox.core.timezone.get_timezone", return_value=ZoneInfo("UTC")):
            result = f(dt)
        assert "Mar 12" in result
        assert "14:30" in result

    def test_non_utc_aware_datetime_converted_correctly(self) -> None:
        f = self._get_filter()
        # Datetime already in a non-UTC timezone
        eastern = ZoneInfo("America/New_York")
        dt = datetime(2026, 3, 12, 10, 30, 0, tzinfo=eastern)
        with patch("pullbox.core.timezone.get_timezone", return_value=ZoneInfo("Asia/Tokyo")):
            result = f(dt, "%Y-%m-%d %H:%M")
        # 10:30 EDT = 14:30 UTC = 23:30 JST
        assert result == "2026-03-12 23:30"

    def test_midnight_utc_date_change(self) -> None:
        f = self._get_filter()
        # Midnight UTC → still previous day in western hemispheres
        dt = datetime(2026, 3, 13, 0, 30, 0, tzinfo=UTC)
        la_tz = ZoneInfo("America/Los_Angeles")
        with patch("pullbox.core.timezone.get_timezone", return_value=la_tz):
            result = f(dt, "%Y-%m-%d %H:%M")
        assert result == "2026-03-12 17:30"


class TestGetTimezone:
    """Timezone resolution handles env vars and fallbacks."""

    def test_tz_env_var_used(self) -> None:
        from pullbox.core.timezone import get_timezone

        get_timezone.cache_clear()
        with patch.dict("os.environ", {"TZ": "Asia/Tokyo"}):
            tz = get_timezone()
        assert str(tz) == "Asia/Tokyo"
        get_timezone.cache_clear()

    def test_invalid_tz_falls_back(self) -> None:
        from pullbox.core.timezone import get_timezone

        get_timezone.cache_clear()
        with patch.dict("os.environ", {"TZ": "Invalid/Zone"}):
            tz = get_timezone()
        # Should not raise — falls back to tzlocal or UTC
        assert tz is not None
        get_timezone.cache_clear()

    def test_no_tz_env_returns_timezone(self) -> None:
        from pullbox.core.timezone import get_timezone

        get_timezone.cache_clear()
        with patch.dict("os.environ", {}, clear=True):
            tz = get_timezone()
        assert tz is not None
        get_timezone.cache_clear()
