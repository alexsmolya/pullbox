"""Security contracts for password hashing and storage boundaries."""

from __future__ import annotations

from pathlib import Path

import bcrypt

from pullbox.core.password_policy import MAX_PASSWORD_BYTES
from pullbox.services.auth_service import BCRYPT_ROUNDS, AuthService

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "pullbox"


def test_bcrypt_cost_factor_is_at_least_security_floor() -> None:
    """Password hashes must use bcrypt cost 12 or stronger."""
    assert BCRYPT_ROUNDS >= 12

    password_hash = AuthService.hash_password("TestPass@123")
    parts = password_hash.split("$")
    assert parts[1] in {"2a", "2b"}
    assert int(parts[2]) >= 12


def test_auth_service_uses_bcrypt_for_password_hashing() -> None:
    """The application password helper must produce bcrypt-verifiable hashes."""
    password = "UniquePass@123"
    password_hash = AuthService.hash_password(password)

    assert password_hash != password
    assert bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def test_hash_password_rejects_inputs_beyond_bcrypt_byte_limit() -> None:
    """Direct hashing calls must not rely on bcrypt's implicit 72-byte truncation."""
    oversized = "Aa1!" + "x" * (MAX_PASSWORD_BYTES - 3)

    try:
        AuthService.hash_password(oversized)
    except ValueError as exc:
        assert f"at most {MAX_PASSWORD_BYTES} bytes" in str(exc)
    else:
        raise AssertionError("Oversized password was hashed")


def test_verify_password_rejects_oversized_input_for_non_matching_hash() -> None:
    """Oversized login attempts should not match unrelated password hashes."""
    password_hash = AuthService.hash_password("Aa1!xxxx")
    oversized = "Aa1!" + "x" * (MAX_PASSWORD_BYTES - 3)

    assert AuthService.verify_password(oversized, password_hash) is False


def test_verify_password_preserves_legacy_bcrypt_truncation_compatibility() -> None:
    """Existing oversized bcrypt hashes remain verifiable after the new hash policy."""
    legacy_password = "Aa1!" + "x" * (MAX_PASSWORD_BYTES - 3)
    legacy_hash = bcrypt.hashpw(
        legacy_password.encode("utf-8")[:MAX_PASSWORD_BYTES],
        bcrypt.gensalt(rounds=BCRYPT_ROUNDS),
    ).decode("utf-8")

    assert AuthService.verify_password(legacy_password, legacy_hash) is True


def test_application_password_hashing_is_centralized() -> None:
    """Only the auth service should call bcrypt hashing/checking primitives."""
    allowed = {Path("services/auth_service.py")}
    offenders: list[str] = []

    for path in SRC_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(SRC_ROOT)
        if relative in allowed:
            continue
        if "bcrypt.hashpw" in text or "bcrypt.checkpw" in text or "bcrypt.gensalt" in text:
            offenders.append(str(relative))

    assert offenders == []
