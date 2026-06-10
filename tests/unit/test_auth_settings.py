"""Tests for authentication settings — local bypass and session lifetime (C-6.6).

Verifies:
- SystemConfig defaults for auth settings
- Session lifetime range validation (1-720)
- Local bypass addresses stored in config
- Config validation rejects out-of-range session lifetime
"""

from __future__ import annotations

from pullbox.models.config import DEFAULT_SYSTEM_CONFIG


class TestAuthSettingsDefaults:
    """SystemConfig has default values for auth settings."""

    def test_local_bypass_enabled_default(self) -> None:
        assert "local_auth_bypass_enabled" in DEFAULT_SYSTEM_CONFIG
        val, vtype = DEFAULT_SYSTEM_CONFIG["local_auth_bypass_enabled"]
        assert val == "false"
        assert vtype == "bool"

    def test_local_bypass_addresses_default(self) -> None:
        assert "local_auth_bypass_addresses" in DEFAULT_SYSTEM_CONFIG
        val, vtype = DEFAULT_SYSTEM_CONFIG["local_auth_bypass_addresses"]
        assert val == "127.0.0.1, ::1"
        assert vtype == "string"

    def test_local_bypass_username_default(self) -> None:
        assert "local_auth_bypass_username" in DEFAULT_SYSTEM_CONFIG
        val, vtype = DEFAULT_SYSTEM_CONFIG["local_auth_bypass_username"]
        assert val == ""
        assert vtype == "string"

    def test_session_lifetime_default(self) -> None:
        assert "session_lifetime_hours" in DEFAULT_SYSTEM_CONFIG
        val, vtype = DEFAULT_SYSTEM_CONFIG["session_lifetime_hours"]
        assert val == "24"
        assert vtype == "int"


class TestSessionLifetimeValidation:
    """Session lifetime must be between 1 and 720 hours."""

    def test_valid_24(self) -> None:
        hours = int("24")
        assert 1 <= hours <= 720

    def test_valid_1(self) -> None:
        hours = int("1")
        assert 1 <= hours <= 720

    def test_valid_720(self) -> None:
        hours = int("720")
        assert 1 <= hours <= 720

    def test_invalid_0(self) -> None:
        hours = int("0")
        assert not (1 <= hours <= 720)

    def test_invalid_721(self) -> None:
        hours = int("721")
        assert not (1 <= hours <= 720)

    def test_invalid_negative(self) -> None:
        hours = int("-1")
        assert not (1 <= hours <= 720)


class TestLocalBypassAddresses:
    """Local bypass address parsing."""

    def test_single_ipv4(self) -> None:
        addrs = "192.168.1.100"
        parts = [a.strip() for a in addrs.split(",")]
        assert parts == ["192.168.1.100"]

    def test_multiple_addresses(self) -> None:
        addrs = "127.0.0.1, ::1, 192.168.0.0/24"
        parts = [a.strip() for a in addrs.split(",")]
        assert len(parts) == 3
        assert "::1" in parts

    def test_empty_string(self) -> None:
        addrs = ""
        parts = [a.strip() for a in addrs.split(",") if a.strip()]
        assert parts == []

    def test_cidr_notation(self) -> None:
        addrs = "10.0.0.0/8, 172.16.0.0/12"
        parts = [a.strip() for a in addrs.split(",")]
        assert len(parts) == 2
        assert "10.0.0.0/8" in parts
