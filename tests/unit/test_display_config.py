"""
Unit tests for display/datetime configuration defaults and parsing.

Validates that display settings exist in DEFAULT_SYSTEM_CONFIG with
correct defaults and that format strings produce expected output.

Run:
    pytest tests/unit/test_display_config.py -v
"""

from __future__ import annotations

from datetime import UTC, datetime

from pullbox.models.config import DEFAULT_SYSTEM_CONFIG


class TestDisplayConfigDefaults:
    """Verify display config keys exist in DEFAULT_SYSTEM_CONFIG."""

    def test_timezone_key_exists(self) -> None:
        assert "display.timezone" in DEFAULT_SYSTEM_CONFIG

    def test_timezone_default_browser(self) -> None:
        value, vtype = DEFAULT_SYSTEM_CONFIG["display.timezone"]
        assert value == "browser"
        assert vtype == "string"

    def test_date_format_key_exists(self) -> None:
        assert "display.date_format" in DEFAULT_SYSTEM_CONFIG

    def test_date_format_default(self) -> None:
        value, vtype = DEFAULT_SYSTEM_CONFIG["display.date_format"]
        assert value == "MMM DD, YYYY"
        assert vtype == "string"

    def test_time_format_key_exists(self) -> None:
        assert "display.time_format" in DEFAULT_SYSTEM_CONFIG

    def test_time_format_default_24h(self) -> None:
        value, vtype = DEFAULT_SYSTEM_CONFIG["display.time_format"]
        assert value == "24h"
        assert vtype == "string"

    def test_show_seconds_key_exists(self) -> None:
        assert "display.show_seconds" in DEFAULT_SYSTEM_CONFIG

    def test_show_seconds_default_false(self) -> None:
        value, vtype = DEFAULT_SYSTEM_CONFIG["display.show_seconds"]
        assert value == "false"
        assert vtype == "bool"


class TestDateFormatPresets:
    """Verify date format presets produce expected output."""

    def test_mmm_dd_yyyy(self) -> None:
        dt = datetime(2026, 3, 22, 14, 30, 0, tzinfo=UTC)
        assert dt.strftime("%b %d, %Y") == "Mar 22, 2026"

    def test_dd_mm_yyyy(self) -> None:
        dt = datetime(2026, 3, 22, 14, 30, 0, tzinfo=UTC)
        assert dt.strftime("%d/%m/%Y") == "22/03/2026"

    def test_yyyy_mm_dd(self) -> None:
        dt = datetime(2026, 3, 22, 14, 30, 0, tzinfo=UTC)
        assert dt.strftime("%Y-%m-%d") == "2026-03-22"

    def test_mm_dd_yyyy(self) -> None:
        dt = datetime(2026, 3, 22, 14, 30, 0, tzinfo=UTC)
        assert dt.strftime("%m/%d/%Y") == "03/22/2026"


class TestTimeFormatPresets:
    """Verify time format presets produce expected output."""

    def test_24h_no_seconds(self) -> None:
        dt = datetime(2026, 3, 22, 14, 5, 37, tzinfo=UTC)
        assert dt.strftime("%H:%M") == "14:05"

    def test_24h_with_seconds(self) -> None:
        dt = datetime(2026, 3, 22, 14, 5, 37, tzinfo=UTC)
        assert dt.strftime("%H:%M:%S") == "14:05:37"

    def test_12h_no_seconds(self) -> None:
        dt = datetime(2026, 3, 22, 14, 5, 37, tzinfo=UTC)
        assert dt.strftime("%I:%M %p") == "02:05 PM"

    def test_12h_with_seconds(self) -> None:
        dt = datetime(2026, 3, 22, 14, 5, 37, tzinfo=UTC)
        assert dt.strftime("%I:%M:%S %p") == "02:05:37 PM"

    def test_12h_midnight(self) -> None:
        dt = datetime(2026, 3, 22, 0, 15, 0, tzinfo=UTC)
        assert dt.strftime("%I:%M %p") == "12:15 AM"

    def test_12h_noon(self) -> None:
        dt = datetime(2026, 3, 22, 12, 0, 0, tzinfo=UTC)
        assert dt.strftime("%I:%M %p") == "12:00 PM"
