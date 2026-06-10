"""Tests for diagnostic package sanitization helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from pullbox.services.diagnostic_sanitizer import REDACTED, coerce_json_safe, redact_value


class _Status(Enum):
    READY = "ready"


def test_redact_value_hides_secret_key_names() -> None:
    assert redact_value("comicvine_api_key", "abc123") == REDACTED
    assert redact_value("db_password", "hunter2") == REDACTED
    assert redact_value("auth_token", "tok_123") == REDACTED
    assert redact_value("log_level", "info") == "info"


def test_coerce_json_safe_converts_common_non_json_types() -> None:
    payload = {
        "path": Path("/config/certs/pullbox.crt"),
        "created_at": datetime(2026, 6, 7, 12, 30, tzinfo=UTC),
        "raw": b"hello\xff",
        "items": [_Status.READY],
    }

    assert coerce_json_safe(payload) == {
        "path": "/config/certs/pullbox.crt",
        "created_at": "2026-06-07T12:30:00+00:00",
        "raw": "hello\ufffd",
        "items": ["_Status.READY"],
    }


def test_coerce_json_safe_redacts_nested_secret_values() -> None:
    assert coerce_json_safe(
        {
            "db_url": "postgresql://user:pass@example.com/pullbox",
            "nested": {"token": "tok_123"},
        }
    ) == {
        "db_url": "postgresql://***REDACTED***@example.com/pullbox",
        "nested": {"token": REDACTED},
    }
