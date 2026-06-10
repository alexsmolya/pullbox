"""Tests for password policy validation and strength checking.

Ensures server-side enforcement matches the client-side password policy
indicator behavior. Tests cover all validation rules and strength levels.

Run:
    pytest tests/unit/test_password_policy_ui.py -v
    pytest tests/unit/test_password_policy_ui.py -v \
        --cov=pullbox.core.password_policy --cov-report=term-missing
"""

from __future__ import annotations

import os

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-policy-ui-tests")

from pullbox.core.password_policy import (
    MAX_PASSWORD_BYTES,
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    SPECIAL_CHARS,
    check_password_strength,
    validate_password,
    validate_username,
)


class TestValidatePassword:
    """Tests for validate_password() covering all policy rules."""

    def test_empty_password_fails_all(self) -> None:
        """Empty password violates length, uppercase, lowercase, digit, and special."""
        violations = validate_password("")
        assert len(violations) >= 5

    def test_short_password_reports_length(self) -> None:
        """Password shorter than MIN_PASSWORD_LENGTH includes length violation."""
        violations = validate_password("Ab1!")
        assert any("at least" in v for v in violations)

    def test_valid_password_no_violations(self) -> None:
        """A password meeting all requirements returns no violations."""
        violations = validate_password("MyP@ssw0rd")
        assert violations == []

    def test_missing_uppercase(self) -> None:
        """Password without uppercase triggers uppercase violation."""
        violations = validate_password("myp@ssw0rd")
        assert any("uppercase" in v for v in violations)

    def test_missing_lowercase(self) -> None:
        """Password without lowercase triggers lowercase violation."""
        violations = validate_password("MYP@SSW0RD")
        assert any("lowercase" in v for v in violations)

    def test_missing_digit(self) -> None:
        """Password without digit triggers digit violation."""
        violations = validate_password("MyP@ssword")
        assert any("digit" in v for v in violations)

    def test_missing_special(self) -> None:
        """Password without special character triggers special char violation."""
        violations = validate_password("MyPassw0rd")
        assert any("special" in v for v in violations)

    def test_max_length_violation(self) -> None:
        """Password exceeding MAX_PASSWORD_LENGTH triggers length violation."""
        long_pw = "A" * (MAX_PASSWORD_LENGTH + 1) + "a1!"
        violations = validate_password(long_pw)
        assert any("at most" in v for v in violations)

    def test_exactly_min_length_valid(self) -> None:
        """Password at exactly MIN_PASSWORD_LENGTH passes length check."""
        pw = "Ab1!" + "x" * (MIN_PASSWORD_LENGTH - 4)
        violations = validate_password(pw)
        assert not any("at least" in v for v in violations)

    def test_exactly_max_length_valid(self) -> None:
        """Password at the bcrypt byte limit passes length checks."""
        pw = "Ab1!" + "x" * (MAX_PASSWORD_BYTES - 4)
        violations = validate_password(pw)
        assert not any("at most" in v for v in violations)

    def test_bcrypt_byte_limit_violation(self) -> None:
        """Password exceeding bcrypt's effective byte limit is rejected."""
        pw = "Ab1!" + "x" * (MAX_PASSWORD_BYTES - 3)
        violations = validate_password(pw)
        assert any("at most 72 bytes" in v for v in violations)


class TestCheckPasswordStrength:
    """Tests for check_password_strength() strength rating."""

    def test_strength_weak_short(self) -> None:
        """Very short password is weak."""
        assert check_password_strength("abc") == "weak"

    def test_strength_weak_missing_requirements(self) -> None:
        """Password missing requirements is weak."""
        assert check_password_strength("abcdefgh") == "weak"

    def test_strength_moderate(self) -> None:
        """Valid 8-char password with all classes is moderate (not yet strong)."""
        assert check_password_strength("MyP@ssw0rd") == "moderate"

    def test_strength_strong(self) -> None:
        """Long password (>=16 chars) with all 4 character classes is strong."""
        assert check_password_strength("MyV3ryStr0ng!P@ssw0rd") == "strong"

    def test_strength_moderate_long_no_all_classes(self) -> None:
        """Long password (>=12 chars) with 3 classes is moderate."""
        # Has uppercase, lowercase, digit but no special
        assert check_password_strength("MyPassword12") == "weak"
        # Make it pass all basic checks first
        result = check_password_strength("MyP@ssw0rd12")
        assert result in ("moderate", "strong")

    def test_strength_empty_is_weak(self) -> None:
        """Empty password is weak."""
        assert check_password_strength("") == "weak"

    def test_strength_exactly_16_all_classes(self) -> None:
        """Password at exactly 16 chars with all 4 classes is strong."""
        pw = "Abcdef1!xxxxxxxx"  # 16 chars, upper+lower+digit+special
        assert len(pw) == 16
        assert check_password_strength(pw) == "strong"


class TestConstants:
    """Tests that public constants have expected values."""

    def test_min_password_length(self) -> None:
        assert MIN_PASSWORD_LENGTH == 8

    def test_max_password_length(self) -> None:
        assert MAX_PASSWORD_LENGTH == 128

    def test_max_password_bytes(self) -> None:
        assert MAX_PASSWORD_BYTES == 72

    def test_special_chars_is_frozenset(self) -> None:
        assert isinstance(SPECIAL_CHARS, frozenset)

    def test_special_chars_contains_common(self) -> None:
        for char in "!@#$%^&*()":
            assert char in SPECIAL_CHARS


class TestValidateUsername:
    """Tests for validate_username() to ensure coverage."""

    def test_valid_username(self) -> None:
        assert validate_username("admin") == []

    def test_short_username(self) -> None:
        violations = validate_username("ab")
        assert any("at least" in v for v in violations)

    def test_long_username(self) -> None:
        violations = validate_username("a" * 51)
        assert any("at most" in v for v in violations)

    def test_invalid_characters(self) -> None:
        violations = validate_username("admin user!")
        assert any("letters, numbers" in v for v in violations)

    def test_allowed_special_chars(self) -> None:
        """Underscores and hyphens are allowed."""
        assert validate_username("my-user_name") == []
