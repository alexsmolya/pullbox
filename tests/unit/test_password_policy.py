"""Unit tests for core.password_policy — password and username validation.

Tests cover minimum/maximum length, character-class requirements, special
character detection, strength rating, and username format validation.

Run:
    pytest tests/unit/test_password_policy.py -v
    pytest tests/unit/test_password_policy.py -v --cov=pullbox.core.password_policy
"""

from pullbox.core.password_policy import (
    MAX_PASSWORD_BYTES,
    check_password_strength,
    validate_password,
    validate_username,
)

# ── Password Length ──────────────────────────────────────────────


class TestPasswordLength:
    """Tests for password length requirements."""

    def test_too_short(self) -> None:
        violations = validate_password("Aa1!xyz")
        assert any("at least 8" in v for v in violations)

    def test_minimum_length_accepted(self) -> None:
        violations = validate_password("Aa1!xyzw")
        assert not any("at least 8" in v for v in violations)

    def test_too_long(self) -> None:
        password = "Aa1!" + "x" * 125  # 129 chars
        violations = validate_password(password)
        assert any("at most 128" in v for v in violations)

    def test_maximum_length_accepted(self) -> None:
        password = "Aa1!" + "x" * 68  # 72 UTF-8 bytes
        violations = validate_password(password)
        assert not any("at most 128" in v for v in violations)

    def test_bcrypt_byte_limit_rejected(self) -> None:
        password = "Aa1!" + "x" * (MAX_PASSWORD_BYTES - 3)  # 73 UTF-8 bytes
        violations = validate_password(password)
        assert any("at most 72 bytes" in v for v in violations)

    def test_multibyte_bcrypt_byte_limit_rejected(self) -> None:
        password = "Aa1!" + "é" * 35  # 74 UTF-8 bytes
        violations = validate_password(password)
        assert any("at most 72 bytes" in v for v in violations)


# ── Character Class Requirements ─────────────────────────────────


class TestCharacterClasses:
    """Tests for required character classes."""

    def test_missing_uppercase(self) -> None:
        violations = validate_password("abcdefg1!")
        assert any("uppercase" in v for v in violations)

    def test_missing_lowercase(self) -> None:
        violations = validate_password("ABCDEFG1!")
        assert any("lowercase" in v for v in violations)

    def test_missing_digit(self) -> None:
        violations = validate_password("Abcdefgh!")
        assert any("digit" in v for v in violations)

    def test_missing_special(self) -> None:
        violations = validate_password("Abcdefg1x")
        assert any("special character" in v for v in violations)

    def test_all_classes_present(self) -> None:
        violations = validate_password("Abcdefg1!")
        assert violations == []


# ── Valid Passwords ──────────────────────────────────────────────


class TestValidPasswords:
    """Tests for passwords that should pass all checks."""

    def test_strong_password(self) -> None:
        assert validate_password("MyStr0ng!Pass") == []

    def test_exact_minimum(self) -> None:
        assert validate_password("Aa1!xxxx") == []

    def test_with_various_special_chars(self) -> None:
        for char in "!@#$%^&*()_+-=[]{}|;":
            assert validate_password(f"Abcdef1{char}") == [], f"Failed for special char: {char}"


# ── Multiple Violations ─────────────────────────────────────────


class TestMultipleViolations:
    """Tests for passwords that fail multiple checks."""

    def test_empty_password(self) -> None:
        violations = validate_password("")
        # Should fail length, uppercase, lowercase, digit, special
        assert len(violations) >= 4

    def test_short_all_lowercase(self) -> None:
        violations = validate_password("abc")
        assert any("at least 8" in v for v in violations)
        assert any("uppercase" in v for v in violations)
        assert any("digit" in v for v in violations)
        assert any("special character" in v for v in violations)


# ── Password Strength Rating ────────────────────────────────────


class TestPasswordStrength:
    """Tests for check_password_strength()."""

    def test_weak_invalid_password(self) -> None:
        assert check_password_strength("short") == "weak"

    def test_weak_barely_valid(self) -> None:
        # Valid but short, all 4 classes
        result = check_password_strength("Aa1!xxxx")
        # 8 chars, 4 classes → moderate (≥3 classes)
        assert result in ("weak", "moderate")

    def test_moderate_12_chars(self) -> None:
        assert check_password_strength("Abcdefghij1!") == "moderate"

    def test_moderate_3_classes(self) -> None:
        # 8 chars but 4 classes
        result = check_password_strength("Abcdef1!")
        assert result == "moderate"

    def test_strong_16_chars_4_classes(self) -> None:
        assert check_password_strength("Abcdefghijklmn1!") == "strong"


# ── Username Validation ─────────────────────────────────────────


class TestUsernameValidation:
    """Tests for validate_username()."""

    def test_valid_username(self) -> None:
        assert validate_username("adam") == []

    def test_valid_with_underscores(self) -> None:
        assert validate_username("my_user_name") == []

    def test_valid_with_hyphens(self) -> None:
        assert validate_username("my-user") == []

    def test_valid_with_numbers(self) -> None:
        assert validate_username("user123") == []

    def test_too_short(self) -> None:
        violations = validate_username("ab")
        assert any("at least 3" in v for v in violations)

    def test_too_long(self) -> None:
        violations = validate_username("x" * 51)
        assert any("at most 50" in v for v in violations)

    def test_invalid_chars_space(self) -> None:
        violations = validate_username("user name")
        assert any("letters, numbers, underscores, and hyphens" in v for v in violations)

    def test_invalid_chars_special(self) -> None:
        violations = validate_username("user@name")
        assert any("letters, numbers, underscores, and hyphens" in v for v in violations)

    def test_minimum_length_accepted(self) -> None:
        assert validate_username("abc") == []

    def test_maximum_length_accepted(self) -> None:
        assert validate_username("x" * 50) == []
