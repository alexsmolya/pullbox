"""Diagnostic package sanitization helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import Enum
from pathlib import Path

from pullbox.core.log_sanitizer import _REDACTED as _LOG_REDACTED
from pullbox.core.log_sanitizer import sanitize_log_value

SECRET_KEYS = frozenset(
    {
        "comicvine_api_key",
        "secret_key",
    }
)

REDACTED = "[REDACTED]"


def coerce_json_safe(value: object, *, key: str | None = None) -> object:
    """Return a JSON-safe, sanitized representation of a diagnostic value."""
    if isinstance(value, Path):
        value = str(value)
    elif isinstance(value, datetime):
        value = value.isoformat()
    elif isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    elif isinstance(value, Mapping):
        return {
            str(child_key): coerce_json_safe(child_value, key=str(child_key))
            for child_key, child_value in value.items()
        }
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [coerce_json_safe(item) for item in value]
    elif isinstance(value, Enum):
        value = str(value)

    sanitized = sanitize_log_value(value, key=key)
    if sanitized == _LOG_REDACTED:
        return REDACTED
    return sanitized


def redact_value(key: str, value: str) -> str:
    """Redact sensitive config values."""
    if key in SECRET_KEYS:
        return REDACTED
    lower_key = key.lower()
    if any(term in lower_key for term in ("password", "token", "secret", "api_key")):
        return REDACTED
    return value
