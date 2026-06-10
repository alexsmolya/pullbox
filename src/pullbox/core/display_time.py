"""Display time formatting — converts UTC datetimes to user-configured format.

Reads display.timezone, display.date_format, display.time_format, and
display.show_seconds from SystemConfig to produce consistently formatted
datetime strings across the entire application.

Used by:
- Jinja `localtime` filter (server-side rendering)
- JavaScript `_pb.*` helpers (client-side rendering via config injection)
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# Map display format tokens to Python strftime codes
_DATE_FORMATS: dict[str, str] = {
    "MMM DD, YYYY": "%b %d, %Y",
    "DD/MM/YYYY": "%d/%m/%Y",
    "YYYY-MM-DD": "%Y-%m-%d",
    "MM/DD/YYYY": "%m/%d/%Y",
}

# Map display format tokens to JavaScript Intl options (for client-side)
_DATE_FORMATS_JS: dict[str, str] = {
    "MMM DD, YYYY": "MMM DD, YYYY",
    "DD/MM/YYYY": "DD/MM/YYYY",
    "YYYY-MM-DD": "YYYY-MM-DD",
    "MM/DD/YYYY": "MM/DD/YYYY",
}

_DEFAULT_DATE_FORMAT = "MMM DD, YYYY"
_DEFAULT_TIME_FORMAT = "24h"
_DEFAULT_SHOW_SECONDS = False
_DEFAULT_SHOW_TIMEZONE = True
_DEFAULT_SHOW_AMPM = True
_DEFAULT_TIMEZONE = "browser"

# ── Cached settings ───────────────────────────────────────────────

_cached_settings: dict[str, str | bool] | None = None
_cache_timestamp: float = 0.0
_CACHE_TTL_SECONDS = 30.0  # Re-read from DB at most every 30s


def get_cached_display_settings() -> dict[str, str | bool]:
    """Return cached display settings (sync, no DB query).

    Returns defaults if cache hasn't been populated yet.
    Used by _ctx() which is synchronous.
    """
    if _cached_settings is not None:
        return _cached_settings
    return {
        "timezone": _DEFAULT_TIMEZONE,
        "date_format": _DEFAULT_DATE_FORMAT,
        "time_format": _DEFAULT_TIME_FORMAT,
        "show_seconds": _DEFAULT_SHOW_SECONDS,
        "show_timezone": _DEFAULT_SHOW_TIMEZONE,
        "show_ampm": _DEFAULT_SHOW_AMPM,
    }


def invalidate_display_cache() -> None:
    """Force next call to refresh from DB."""
    global _cached_settings, _cache_timestamp
    _cached_settings = None
    _cache_timestamp = 0.0


def get_display_timezone_name(
    *,
    db_value: str = _DEFAULT_TIMEZONE,
) -> str:
    """Resolve the effective display timezone name.

    Priority: TZ env var → db_value → "browser" (auto-detect).
    """
    env_tz = os.environ.get("TZ")
    if env_tz:
        return env_tz
    return db_value if db_value else _DEFAULT_TIMEZONE


def get_display_timezone(
    *,
    db_value: str = _DEFAULT_TIMEZONE,
) -> ZoneInfo | None:
    """Resolve the effective display timezone as a ZoneInfo object.

    Returns None when timezone is "browser" (client-side auto-detect).
    """
    name = get_display_timezone_name(db_value=db_value)
    if name == "browser":
        return None
    try:
        return ZoneInfo(name)
    except (KeyError, ValueError):
        return ZoneInfo("UTC")


def build_strftime_format(
    *,
    date_format: str = _DEFAULT_DATE_FORMAT,
    time_format: str = _DEFAULT_TIME_FORMAT,
    show_seconds: bool = _DEFAULT_SHOW_SECONDS,
    show_timezone: bool = _DEFAULT_SHOW_TIMEZONE,
    show_ampm: bool = _DEFAULT_SHOW_AMPM,
) -> str:
    """Build a Python strftime format string from display settings."""
    date_part = _DATE_FORMATS.get(date_format, _DATE_FORMATS[_DEFAULT_DATE_FORMAT])
    time_part = build_time_strftime_format(
        time_format=time_format,
        show_seconds=show_seconds,
        show_timezone=show_timezone,
        show_ampm=show_ampm,
    )
    return f"{date_part}, {time_part}"


def build_time_strftime_format(
    *,
    time_format: str = _DEFAULT_TIME_FORMAT,
    show_seconds: bool = _DEFAULT_SHOW_SECONDS,
    show_timezone: bool = _DEFAULT_SHOW_TIMEZONE,
    show_ampm: bool = _DEFAULT_SHOW_AMPM,
) -> str:
    """Build a Python strftime format string for time-only display."""
    if time_format == "12h":
        ampm = " %p" if show_ampm else ""
        time_part = f"%I:%M:%S{ampm}" if show_seconds else f"%I:%M{ampm}"
    else:
        time_part = "%H:%M:%S" if show_seconds else "%H:%M"

    tz_part = " %Z" if show_timezone else ""
    return f"{time_part}{tz_part}"


def _to_local_datetime(value: datetime, *, timezone: ZoneInfo | None = None) -> datetime:
    """Convert a datetime to the configured display timezone."""
    tz = timezone or ZoneInfo("UTC")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC).astimezone(tz)
    return value.astimezone(tz)


def format_datetime(
    value: datetime | date | None,
    *,
    date_format: str = _DEFAULT_DATE_FORMAT,
    time_format: str = _DEFAULT_TIME_FORMAT,
    show_seconds: bool = _DEFAULT_SHOW_SECONDS,
    show_timezone: bool = _DEFAULT_SHOW_TIMEZONE,
    show_ampm: bool = _DEFAULT_SHOW_AMPM,
    timezone: ZoneInfo | None = None,
) -> str:
    """Format a datetime using the display settings.

    Args:
        value: UTC datetime to format. None returns "\u2014".
        timezone: Target timezone. None uses UTC.
    """
    if value is None:
        return "\u2014"
    if isinstance(value, date) and not isinstance(value, datetime):
        date_part = _DATE_FORMATS.get(date_format, _DATE_FORMATS[_DEFAULT_DATE_FORMAT])
        return value.strftime(date_part)

    local_dt = _to_local_datetime(value, timezone=timezone)
    fmt = build_strftime_format(
        date_format=date_format,
        time_format=time_format,
        show_seconds=show_seconds,
        show_timezone=show_timezone,
        show_ampm=show_ampm,
    )
    return local_dt.strftime(fmt)


def format_time(
    value: datetime | None,
    *,
    time_format: str = _DEFAULT_TIME_FORMAT,
    show_seconds: bool = _DEFAULT_SHOW_SECONDS,
    show_timezone: bool = _DEFAULT_SHOW_TIMEZONE,
    show_ampm: bool = _DEFAULT_SHOW_AMPM,
    timezone: ZoneInfo | None = None,
) -> str:
    """Format a datetime as time-only using the display settings."""
    if value is None:
        return "\u2014"

    local_dt = _to_local_datetime(value, timezone=timezone)
    fmt = build_time_strftime_format(
        time_format=time_format,
        show_seconds=show_seconds,
        show_timezone=show_timezone,
        show_ampm=show_ampm,
    )
    return local_dt.strftime(fmt)


async def load_display_settings(session: AsyncSession) -> dict[str, str | bool]:
    """Load display settings from SystemConfig and update the cache.

    Returns a dict with keys: timezone, date_format, time_format, show_seconds.
    """
    import time

    global _cached_settings, _cache_timestamp

    # Return cache if fresh
    now = time.monotonic()
    if _cached_settings is not None and (now - _cache_timestamp) < _CACHE_TTL_SECONDS:
        return _cached_settings

    from pullbox.models.config import SystemConfig

    keys = [
        "display.timezone",
        "display.date_format",
        "display.time_format",
        "display.show_seconds",
        "display.show_timezone",
        "display.show_ampm",
    ]

    _bool_keys = {"show_seconds", "show_timezone", "show_ampm"}

    settings: dict[str, str | bool] = {
        "timezone": _DEFAULT_TIMEZONE,
        "date_format": _DEFAULT_DATE_FORMAT,
        "time_format": _DEFAULT_TIME_FORMAT,
        "show_seconds": _DEFAULT_SHOW_SECONDS,
        "show_timezone": _DEFAULT_SHOW_TIMEZONE,
        "show_ampm": _DEFAULT_SHOW_AMPM,
    }

    for key in keys:
        row = await session.get(SystemConfig, key)
        if row:
            short_key = key.split(".", 1)[1]
            if short_key in _bool_keys:
                settings[short_key] = row.value.lower() == "true"
            else:
                settings[short_key] = row.value

    # Apply TZ env var override
    settings["timezone"] = get_display_timezone_name(
        db_value=str(settings["timezone"]),
    )

    _cached_settings = settings
    _cache_timestamp = now
    return settings
