"""Timezone resolution — reads TZ env var, falls back to system detection."""

import os
from functools import lru_cache
from zoneinfo import ZoneInfo

import structlog

logger = structlog.get_logger(__name__)


@lru_cache(maxsize=1)
def get_timezone() -> ZoneInfo:
    """Resolve the application timezone.

    Priority: TZ env var -> tzlocal auto-detection -> UTC fallback.
    """
    tz_name = os.environ.get("TZ")
    if tz_name:
        try:
            return ZoneInfo(tz_name)
        except (KeyError, ValueError):
            logger.warning("invalid_tz_env_var", tz=tz_name)

    try:
        from tzlocal import get_localzone

        tz = get_localzone()
        if isinstance(tz, ZoneInfo):
            return tz
        # tzlocal may return a different type on older versions; convert via key
        return ZoneInfo(str(tz))
    except Exception:
        logger.warning("tzlocal_detection_failed_using_utc")
        return ZoneInfo("UTC")
