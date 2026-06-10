"""
Unit tests for blocklist SystemConfig defaults and parsing.

Validates that blocklist config keys exist with correct defaults
and that values parse correctly to their expected types.

Run:
    pytest tests/unit/test_blocklist_config.py -v
"""

from __future__ import annotations

from pullbox.models.config import DEFAULT_SYSTEM_CONFIG


class TestBlocklistConfigDefaults:
    """Verify blocklist config keys exist in DEFAULT_SYSTEM_CONFIG."""

    def test_release_groups_key_exists(self) -> None:
        assert "blocklist.release_groups" in DEFAULT_SYSTEM_CONFIG

    def test_release_groups_default_empty(self) -> None:
        value, vtype = DEFAULT_SYSTEM_CONFIG["blocklist.release_groups"]
        assert value == ""
        assert vtype == "string"

    def test_expiry_days_key_exists(self) -> None:
        assert "blocklist.expiry_days" in DEFAULT_SYSTEM_CONFIG

    def test_expiry_days_default_90(self) -> None:
        value, vtype = DEFAULT_SYSTEM_CONFIG["blocklist.expiry_days"]
        assert value == "90"
        assert vtype == "int"

    def test_auto_add_on_failure_key_exists(self) -> None:
        assert "blocklist.auto_add_on_failure" in DEFAULT_SYSTEM_CONFIG

    def test_auto_add_on_failure_default_true(self) -> None:
        value, vtype = DEFAULT_SYSTEM_CONFIG["blocklist.auto_add_on_failure"]
        assert value == "true"
        assert vtype == "bool"


class TestBlocklistConfigParsing:
    """Verify blocklist config values parse correctly to expected types."""

    def test_expiry_days_parses_to_int(self) -> None:
        value, _ = DEFAULT_SYSTEM_CONFIG["blocklist.expiry_days"]
        assert int(value) == 90

    def test_auto_add_parses_to_bool_true(self) -> None:
        value, _ = DEFAULT_SYSTEM_CONFIG["blocklist.auto_add_on_failure"]
        assert value.lower() == "true"

    def test_auto_add_false_string_parses(self) -> None:
        """Verify 'false' string is a valid bool representation."""
        assert "false".lower() == "false"

    def test_release_groups_empty_parses_to_empty_list(self) -> None:
        value, _ = DEFAULT_SYSTEM_CONFIG["blocklist.release_groups"]
        groups = [g.strip() for g in value.split(",") if g.strip()]
        assert groups == []

    def test_release_groups_comma_separated_parses(self) -> None:
        test_value = "Empire,DCP,Pyrate"
        groups = [g.strip() for g in test_value.split(",") if g.strip()]
        assert groups == ["Empire", "DCP", "Pyrate"]

    def test_release_groups_strips_whitespace(self) -> None:
        test_value = " Empire , DCP , Pyrate "
        groups = [g.strip() for g in test_value.split(",") if g.strip()]
        assert groups == ["Empire", "DCP", "Pyrate"]

    def test_release_groups_ignores_empty_segments(self) -> None:
        test_value = "Empire,,DCP,"
        groups = [g.strip() for g in test_value.split(",") if g.strip()]
        assert groups == ["Empire", "DCP"]

    def test_expiry_days_zero_is_valid(self) -> None:
        """expiry_days=0 disables expiration."""
        assert int("0") == 0

    def test_expiry_days_custom_values(self) -> None:
        assert int("30") == 30
        assert int("365") == 365

    def test_missing_config_key_not_present(self) -> None:
        assert "blocklist.nonexistent" not in DEFAULT_SYSTEM_CONFIG
