"""
Unit tests for display_time formatting module.

Covers timezone resolution, strftime format building, and datetime
formatting with various display settings.

Run:
    pytest tests/unit/test_display_time.py -v
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from pullbox.core.display_time import (
    build_strftime_format,
    build_time_strftime_format,
    format_datetime,
    format_time,
    get_display_timezone,
    get_display_timezone_name,
)


class TestGetDisplayTimezoneName:
    """Tests for timezone name resolution."""

    def test_default_is_browser(self) -> None:
        # Ensure TZ env isn't set for this test
        old_tz = os.environ.pop("TZ", None)
        try:
            assert get_display_timezone_name() == "browser"
        finally:
            if old_tz:
                os.environ["TZ"] = old_tz

    def test_db_value_used(self) -> None:
        old_tz = os.environ.pop("TZ", None)
        try:
            assert get_display_timezone_name(db_value="America/New_York") == "America/New_York"
        finally:
            if old_tz:
                os.environ["TZ"] = old_tz

    def test_env_overrides_db(self) -> None:
        old_tz = os.environ.get("TZ")
        os.environ["TZ"] = "Europe/London"
        try:
            assert get_display_timezone_name(db_value="America/New_York") == "Europe/London"
        finally:
            if old_tz:
                os.environ["TZ"] = old_tz
            else:
                os.environ.pop("TZ", None)

    def test_empty_db_value_returns_default(self) -> None:
        old_tz = os.environ.pop("TZ", None)
        try:
            assert get_display_timezone_name(db_value="") == "browser"
        finally:
            if old_tz:
                os.environ["TZ"] = old_tz


class TestGetDisplayTimezone:
    """Tests for ZoneInfo resolution."""

    def test_browser_returns_none(self) -> None:
        result = get_display_timezone(db_value="browser")
        assert result is None

    def test_valid_timezone(self) -> None:
        result = get_display_timezone(db_value="America/New_York")
        assert result is not None
        assert str(result) == "America/New_York"

    def test_utc(self) -> None:
        result = get_display_timezone(db_value="UTC")
        assert result is not None
        assert str(result) == "UTC"

    def test_invalid_timezone_falls_back_to_utc(self) -> None:
        result = get_display_timezone(db_value="Invalid/Timezone")
        assert result is not None
        assert str(result) == "UTC"


class TestBuildStrftimeFormat:
    """Tests for strftime format string building."""

    def test_default_24h_no_seconds(self) -> None:
        fmt = build_strftime_format()
        assert "%H:%M" in fmt
        assert "%S" not in fmt
        assert "%Z" in fmt

    def test_24h_with_seconds(self) -> None:
        fmt = build_strftime_format(show_seconds=True)
        assert "%H:%M:%S" in fmt

    def test_12h_no_seconds(self) -> None:
        fmt = build_strftime_format(time_format="12h")
        assert "%I:%M %p" in fmt
        assert "%S" not in fmt

    def test_12h_with_seconds(self) -> None:
        fmt = build_strftime_format(time_format="12h", show_seconds=True)
        assert "%I:%M:%S %p" in fmt

    def test_date_format_iso(self) -> None:
        fmt = build_strftime_format(date_format="YYYY-MM-DD")
        assert "%Y-%m-%d" in fmt

    def test_date_format_eu(self) -> None:
        fmt = build_strftime_format(date_format="DD/MM/YYYY")
        assert "%d/%m/%Y" in fmt

    def test_no_tz(self) -> None:
        fmt = build_strftime_format(show_timezone=False)
        assert "%Z" not in fmt


class TestBuildTimeStrftimeFormat:
    """Tests for time-only strftime format string building."""

    def test_default_24h_no_seconds(self) -> None:
        fmt = build_time_strftime_format()
        assert fmt == "%H:%M %Z"

    def test_24h_with_seconds(self) -> None:
        fmt = build_time_strftime_format(show_seconds=True)
        assert fmt == "%H:%M:%S %Z"

    def test_12h_with_ampm(self) -> None:
        fmt = build_time_strftime_format(time_format="12h")
        assert fmt == "%I:%M %p %Z"

    def test_12h_without_ampm(self) -> None:
        fmt = build_time_strftime_format(time_format="12h", show_ampm=False)
        assert fmt == "%I:%M %Z"

    def test_no_timezone(self) -> None:
        fmt = build_time_strftime_format(show_timezone=False)
        assert fmt == "%H:%M"


class TestFormatDatetime:
    """Tests for format_datetime output."""

    def test_none_returns_dash(self) -> None:
        assert format_datetime(None) == "\u2014"

    def test_default_format_utc(self) -> None:
        dt = datetime(2026, 3, 22, 14, 30, 45, tzinfo=UTC)
        result = format_datetime(dt)
        assert "Mar 22, 2026" in result
        assert "14:30" in result
        assert "UTC" in result

    def test_24h_with_seconds(self) -> None:
        dt = datetime(2026, 3, 22, 14, 5, 37, tzinfo=UTC)
        result = format_datetime(dt, show_seconds=True)
        assert "14:05:37" in result

    def test_12h_format(self) -> None:
        dt = datetime(2026, 3, 22, 14, 30, 0, tzinfo=UTC)
        result = format_datetime(dt, time_format="12h")
        assert "02:30 PM" in result

    def test_iso_date_format(self) -> None:
        dt = datetime(2026, 3, 22, 14, 30, 0, tzinfo=UTC)
        result = format_datetime(dt, date_format="YYYY-MM-DD")
        assert "2026-03-22" in result

    def test_timezone_conversion(self) -> None:
        dt = datetime(2026, 3, 22, 14, 30, 0, tzinfo=UTC)
        eastern = ZoneInfo("America/New_York")
        result = format_datetime(dt, timezone=eastern)
        # UTC 14:30 = EDT 10:30
        assert "10:30" in result

    def test_naive_datetime_treated_as_utc(self) -> None:
        dt = datetime(2026, 3, 22, 14, 30, 0)  # naive
        result = format_datetime(dt)
        assert "14:30" in result
        assert "UTC" in result

    @pytest.mark.parametrize(
        "date_fmt",
        ["MMM DD, YYYY", "DD/MM/YYYY", "YYYY-MM-DD", "MM/DD/YYYY"],
    )
    def test_all_date_formats_produce_output(self, date_fmt: str) -> None:
        dt = datetime(2026, 3, 22, 14, 30, 0, tzinfo=UTC)
        result = format_datetime(dt, date_format=date_fmt)
        assert len(result) > 10  # reasonable output
        assert "2026" in result or "26" in result


class TestFormatTime:
    """Tests for time-only display formatting."""

    def test_none_returns_dash(self) -> None:
        assert format_time(None) == "\u2014"

    def test_24h_with_seconds(self) -> None:
        dt = datetime(2026, 3, 22, 14, 5, 37, tzinfo=UTC)
        result = format_time(dt, show_seconds=True, show_timezone=False)
        assert result == "14:05:37"

    def test_12h_format_with_ampm(self) -> None:
        dt = datetime(2026, 3, 22, 14, 30, 0, tzinfo=UTC)
        result = format_time(dt, time_format="12h", show_timezone=False)
        assert result == "02:30 PM"

    def test_timezone_conversion(self) -> None:
        dt = datetime(2026, 3, 22, 14, 30, 0, tzinfo=UTC)
        eastern = ZoneInfo("America/New_York")
        result = format_time(dt, timezone=eastern, show_timezone=False)
        assert result == "10:30"

    def test_naive_datetime_treated_as_utc(self) -> None:
        dt = datetime(2026, 3, 22, 14, 30, 0)
        result = format_time(dt, show_timezone=False)
        assert result == "14:30"
