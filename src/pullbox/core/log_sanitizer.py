"""Sensitive data log sanitizer — shared helpers for redacting secrets.

Provides a structlog processor plus reusable sanitization helpers that scrub
sensitive data before it reaches renderers or DB-backed log stores. Handles
key-name matching, URL query parameter redaction, URL/DSN basic-auth
redaction, Bearer token stripping, and nested dictionary/list sanitization.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

import structlog  # noqa: TC002 — used at runtime in processor signatures

_REDACTED = "***REDACTED***"

# Key names (lowercased) that indicate a sensitive value
_SENSITIVE_KEY_PATTERNS: frozenset[str] = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "api-key",
        "credential",
        "authorization",
        "auth_token",
        "secret_key",
        "private_key",
        "access_key",
    }
)

# Key names that look sensitive but are NOT secrets
_EXCLUDED_KEY_PATTERNS: frozenset[str] = frozenset(
    {
        "csrf_token",
        "token_type",
    }
)

# URL query parameters that contain secrets
_URL_PARAM_RE = re.compile(
    r"([?&])(apikey|api_key|api-key|token|password|secret)=([^&\s]*)",
    re.IGNORECASE,
)

# Secret-looking key/value assignments in free-form exception or provider text.
_SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"\b(password|passwd|apikey|api_key|api-key|secret|token|authorization|auth_token|"
    r"secret_key|private_key|access_key)=([^\s&,'\"\\)]+)",
    re.IGNORECASE,
)

# Credentials embedded in a URL or DSN, e.g. postgres://user:pass@host/db
_URL_AUTH_RE = re.compile(r"([a-z][a-z0-9+.\-]*://)([^/\s@]+)@", re.IGNORECASE)

# Bearer tokens in header values
_BEARER_RE = re.compile(r"(Bearer\s+)\S+", re.IGNORECASE)

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _is_sensitive_key(key: str) -> bool:
    """Return True if a key name indicates a sensitive field."""
    lower = key.lower()
    if any(excl in lower for excl in _EXCLUDED_KEY_PATTERNS):
        return False
    return any(pat in lower for pat in _SENSITIVE_KEY_PATTERNS)


def _sanitize_value(value: str) -> str:
    """Redact sensitive patterns found inside a string value."""
    result = value
    if _URL_AUTH_RE.search(result):
        result = _URL_AUTH_RE.sub(rf"\1{_REDACTED}@", result)
    if _URL_PARAM_RE.search(result):
        result = _URL_PARAM_RE.sub(rf"\1\2={_REDACTED}", result)
    if _SENSITIVE_ASSIGNMENT_RE.search(result):
        result = _SENSITIVE_ASSIGNMENT_RE.sub(rf"\1={_REDACTED}", result)
    if "bearer " in result.lower():
        result = _BEARER_RE.sub(rf"\1{_REDACTED}", result)
    result = result.replace("\r", "\\r").replace("\n", "\\n").replace("\t", "\\t")
    result = _CONTROL_CHARS_RE.sub(lambda match: f"\\x{ord(match.group(0)):02x}", result)
    return result


_MAX_SANITIZE_DEPTH = 5


def _sanitize_dict(d: dict[str, object], _depth: int = 0) -> dict[str, object]:
    """Recursively sanitize a nested dictionary up to a depth limit."""
    cleaned: dict[str, object] = {}
    for key, value in d.items():
        cleaned[key] = sanitize_log_value(value, key=key, depth=_depth)
    return cleaned


def sanitize_log_string(value: str) -> str:
    """Return a sanitized string safe to persist or render in logs."""
    return _sanitize_value(value)


def sanitize_log_value(
    value: object,
    *,
    key: str | None = None,
    depth: int = 0,
) -> object:
    """Recursively sanitize one value for logging sinks."""
    if isinstance(value, str):
        if key is not None and _is_sensitive_key(key):
            return _REDACTED
        return _sanitize_value(value)

    if isinstance(value, Mapping) and depth < _MAX_SANITIZE_DEPTH:
        cleaned: dict[str, object] = {}
        for nested_key, nested_value in value.items():
            cleaned[str(nested_key)] = sanitize_log_value(
                nested_value,
                key=str(nested_key),
                depth=depth + 1,
            )
        return cleaned

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if depth >= _MAX_SANITIZE_DEPTH:
            return list(value)
        return [sanitize_log_value(item, depth=depth + 1) for item in value]

    return value


def sanitize_log_mapping(data: Mapping[str, Any]) -> dict[str, object]:
    """Return a sanitized shallow-or-nested mapping for log persistence."""
    return {
        str(key): sanitize_log_value(value, key=str(key), depth=0) for key, value in data.items()
    }


def sanitize_sensitive_data(
    _logger: object,
    _method_name: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    """Structlog processor: redact sensitive values from log events.

    Handles three categories of sensitive data:
    1. Key names matching known secret patterns (password, api_key, etc.)
    2. String values containing URL query parameters with secrets
    3. String values containing Bearer tokens
    4. Recursively nested dictionaries (up to depth limit)
    """
    for key in list(event_dict):
        event_dict[key] = sanitize_log_value(event_dict[key], key=key)

    return event_dict
