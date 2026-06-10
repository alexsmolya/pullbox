"""Unit tests for core.log_sanitizer — sensitive data redaction in log events.

Tests cover key-name redaction, URL parameter scrubbing, Bearer token
stripping, nested dict handling, exclusion patterns, and performance.

Run:
    pytest tests/unit/test_log_sanitizer.py -v
    pytest tests/unit/test_log_sanitizer.py -v --cov=pullbox.core.log_sanitizer
"""

from __future__ import annotations

import time

from pullbox.core.log_sanitizer import sanitize_sensitive_data

_R = "***REDACTED***"


def _run(event_dict: dict[str, object]) -> dict[str, object]:
    """Shortcut to invoke the processor."""
    return sanitize_sensitive_data(None, "info", event_dict)


# ── Key-Name Redaction ────────────────────────────────────────────


class TestKeyNameRedaction:
    """Tests for redacting values based on key names."""

    def test_redacts_password_key(self) -> None:
        result = _run({"password": "hunter2"})
        assert result["password"] == _R

    def test_redacts_api_key_key(self) -> None:
        result = _run({"api_key": "abc123"})
        assert result["api_key"] == _R

    def test_redacts_secret_key(self) -> None:
        result = _run({"secret": "s3cret"})
        assert result["secret"] == _R

    def test_redacts_token_key(self) -> None:
        result = _run({"token": "eyJhb..."})
        assert result["token"] == _R

    def test_redacts_authorization_key(self) -> None:
        result = _run({"authorization": "Bearer abc"})
        assert result["authorization"] == _R

    def test_redacts_private_key(self) -> None:
        result = _run({"private_key": "-----BEGIN RSA-----"})
        assert result["private_key"] == _R

    def test_redacts_case_insensitive_key(self) -> None:
        result = _run({"API_KEY": "abc"})
        assert result["API_KEY"] == _R

    def test_redacts_compound_key(self) -> None:
        result = _run({"user_password_hash": "abc"})
        assert result["user_password_hash"] == _R


# ── Exclusion Patterns ────────────────────────────────────────────


class TestExclusionPatterns:
    """Tests for keys that should NOT be redacted."""

    def test_preserves_csrf_token(self) -> None:
        result = _run({"csrf_token": "abc123"})
        assert result["csrf_token"] == "abc123"

    def test_preserves_token_type(self) -> None:
        result = _run({"token_type": "Bearer"})
        assert result["token_type"] == "Bearer"


# ── URL Parameter Redaction ───────────────────────────────────────


class TestURLParameterRedaction:
    """Tests for scrubbing secrets from URL query parameters in values."""

    def test_redacts_apikey_in_url_value(self) -> None:
        result = _run({"url": "http://host/api?apikey=abc123"})
        assert result["url"] == f"http://host/api?apikey={_R}"

    def test_redacts_api_key_in_url_value(self) -> None:
        result = _run({"url": "http://host/api?api_key=secret456"})
        assert result["url"] == f"http://host/api?api_key={_R}"

    def test_redacts_token_in_url_value(self) -> None:
        result = _run({"url": "http://host/api?token=xyz&mode=search"})
        assert f"token={_R}" in result["url"]
        assert "mode=search" in result["url"]

    def test_redacts_multiple_params(self) -> None:
        result = _run({"url": "http://host?apikey=abc&password=def"})
        assert f"apikey={_R}" in result["url"]
        assert f"password={_R}" in result["url"]

    def test_preserves_safe_url_params(self) -> None:
        result = _run({"url": "http://host/api?mode=search&name=Batman"})
        assert result["url"] == "http://host/api?mode=search&name=Batman"

    def test_redacts_basic_auth_in_url_value(self) -> None:
        result = _run({"url": "http://user:pass@example.com/api"})
        assert result["url"] == f"http://{_R}@example.com/api"

    def test_redacts_credentials_in_dsn(self) -> None:
        result = _run({"db_url": "postgresql://pullbox:secretpass@db.internal/pullbox"})
        assert result["db_url"] == f"postgresql://{_R}@db.internal/pullbox"


# ── Bearer Token Redaction ────────────────────────────────────────


class TestBearerTokenRedaction:
    """Tests for stripping Bearer tokens from string values."""

    def test_redacts_bearer_in_value(self) -> None:
        result = _run({"header": "Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig"})
        assert result["header"] == f"Bearer {_R}"

    def test_redacts_bearer_case_insensitive(self) -> None:
        result = _run({"auth": "bearer my-secret-token"})
        assert result["auth"] == f"bearer {_R}"


class TestFreeFormSecretAssignmentRedaction:
    """Tests for scrubbing key=value secrets from free-form text."""

    def test_redacts_api_key_assignment_in_exception_text(self) -> None:
        result = _run({"exception": "ValueError: provider failed api_key=secret123"})
        assert result["exception"] == f"ValueError: provider failed api_key={_R}"

    def test_redacts_password_assignment_without_url_prefix(self) -> None:
        result = _run({"message": "login failed password=hunter2, retrying"})
        assert result["message"] == f"login failed password={_R}, retrying"

    def test_redacts_secret_assignment_before_escaped_newline(self) -> None:
        result = _run({"exception": "RuntimeError: secret=abc123\\nnext-line"})
        assert result["exception"] == f"RuntimeError: secret={_R}\\nnext-line"


# ── Normal Values Preserved ───────────────────────────────────────


class TestPreservesNormalValues:
    """Tests that non-sensitive data passes through unchanged."""

    def test_preserves_normal_keys(self) -> None:
        result = _run({"username": "adam", "event": "login", "level": "info"})
        assert result["username"] == "adam"
        assert result["event"] == "login"
        assert result["level"] == "info"

    def test_preserves_non_string_values(self) -> None:
        result = _run({"count": 42, "ratio": 3.14, "active": True, "data": None})
        assert result["count"] == 42
        assert result["ratio"] == 3.14
        assert result["active"] is True
        assert result["data"] is None


class TestLogInjectionNeutralization:
    """Tests for neutralizing control characters before log persistence."""

    def test_neutralizes_newline_in_log_value(self) -> None:
        result = _run({"event": "search_failed\nlevel=error"})
        assert result["event"] == "search_failed\\nlevel=error"

    def test_neutralizes_carriage_return_in_nested_value(self) -> None:
        result = _run({"request": {"path": "/safe\rX-Injected: yes"}})
        nested = result["request"]
        assert isinstance(nested, dict)
        assert nested["path"] == "/safe\\rX-Injected: yes"

    def test_neutralizes_non_printable_control_character(self) -> None:
        result = _run({"message": "prefix\x00suffix"})
        assert result["message"] == "prefix\\x00suffix"


# ── Nested Dict Handling ──────────────────────────────────────────


class TestNestedDictHandling:
    """Tests for sanitizing nested dictionaries."""

    def test_handles_nested_dict(self) -> None:
        result = _run({"outer": {"password": "secret", "username": "adam"}})
        nested = result["outer"]
        assert isinstance(nested, dict)
        assert nested["password"] == _R
        assert nested["username"] == "adam"

    def test_nested_dict_url_redaction(self) -> None:
        result = _run({"request": {"url": "http://host?apikey=abc"}})
        nested = result["request"]
        assert isinstance(nested, dict)
        assert f"apikey={_R}" in nested["url"]


# ── Deep Nesting ─────────────────────────────────────────────────


class TestDeepNesting:
    """Tests for recursive sanitization of deeply nested dictionaries."""

    def test_two_level_nested_password(self) -> None:
        result = _run({"data": {"inner": {"password": "secret"}}})
        assert result["data"]["inner"]["password"] == _R

    def test_three_level_nested_token(self) -> None:
        result = _run({"a": {"b": {"c": {"token": "xyz"}}}})
        assert result["a"]["b"]["c"]["token"] == _R

    def test_nested_url_param_redaction(self) -> None:
        result = _run({"outer": {"inner": {"url": "http://host?apikey=abc"}}})
        assert f"apikey={_R}" in result["outer"]["inner"]["url"]

    def test_depth_limit_stops_recursion(self) -> None:
        """Nesting beyond the depth limit should not be sanitized."""
        # Build a dict nested 7 levels deep with a secret at the bottom
        d: dict[str, object] = {"password": "deep_secret"}
        for i in range(7):
            d = {f"level_{i}": d}
        result = _run(d)
        # Walk down to the bottom
        node = result
        for i in range(6, -1, -1):
            node = node[f"level_{i}"]
        # At depth 7+, the password should NOT be redacted (beyond limit)
        assert node["password"] == "deep_secret"

    def test_depth_limit_boundary_still_sanitizes(self) -> None:
        """At exactly the depth limit, sanitization should still apply."""
        # Build a dict nested 4 levels deep (within default limit of 5)
        d: dict[str, object] = {"password": "at_boundary"}
        for i in range(4):
            d = {f"level_{i}": d}
        result = _run(d)
        node = result
        for i in range(3, -1, -1):
            node = node[f"level_{i}"]
        assert node["password"] == _R

    def test_nested_non_dict_values_preserved(self) -> None:
        result = _run({"data": {"count": 42, "active": True, "name": "test"}})
        assert result["data"]["count"] == 42
        assert result["data"]["active"] is True
        assert result["data"]["name"] == "test"

    def test_mixed_nested_sensitive_and_safe(self) -> None:
        result = _run(
            {
                "request": {
                    "headers": {"authorization": "Bearer xyz", "content_type": "json"},
                    "body": {"username": "adam"},
                }
            }
        )
        assert result["request"]["headers"]["authorization"] == _R
        assert result["request"]["headers"]["content_type"] == "json"
        assert result["request"]["body"]["username"] == "adam"


# ── Edge Cases ────────────────────────────────────────────────────


class TestEdgeCases:
    """Tests for edge cases and empty inputs."""

    def test_handles_empty_event_dict(self) -> None:
        result = _run({})
        assert result == {}

    def test_handles_multiple_sensitive_keys(self) -> None:
        result = _run({"password": "pw", "api_key": "ak", "secret": "sc"})
        assert result["password"] == _R
        assert result["api_key"] == _R
        assert result["secret"] == _R

    def test_performance(self) -> None:
        """Event dict with 50 keys should be processed quickly."""
        event_dict: dict[str, object] = {f"key_{i}": f"value_{i}" for i in range(50)}
        event_dict["password"] = "secret"
        event_dict["url"] = "http://host?apikey=abc123"

        start = time.monotonic()
        for _ in range(1000):
            _run(dict(event_dict))
        elapsed = time.monotonic() - start

        # 1000 iterations with 52 keys — generous limit for CI runners
        assert elapsed < 5.0
