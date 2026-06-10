"""Unit tests for scripts/reset_password.py — CLI password reset.

Tests cover the ``reset_password()`` core function: successful resets,
password policy enforcement, nonexistent users, session invalidation,
inactive accounts, and idempotent re-resets.

Run:
    pytest tests/unit/test_reset_password.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from pullbox.models.user import User
from pullbox.services.auth_service import AuthService

# Make scripts/ importable so we can import reset_password.
_scripts_dir = str(Path(__file__).resolve().parent.parent.parent / "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from reset_password import reset_password  # noqa: E402

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# ── Helpers ─────────────────────────────────────────────────────


async def _create_user(
    session: AsyncSession,
    username: str = "admin",
    password: str = "OldPass@123",
    *,
    is_active: bool = True,
    session_version: int = 0,
) -> User:
    """Insert a test user directly (bypasses AuthService to control fields)."""
    user = User(
        username=username,
        password_hash=AuthService.hash_password(password),
        is_active=is_active,
        session_version=session_version,
    )
    session.add(user)
    await session.flush()
    return user


# ── Happy Path ──────────────────────────────────────────────────


class TestResetPasswordSuccess:
    """Successful password reset scenarios."""

    @pytest.mark.asyncio
    async def test_updates_password_hash(self, db_session: AsyncSession) -> None:
        user = await _create_user(db_session)
        old_hash = user.password_hash

        await reset_password(db_session, "admin", "NewPass@456")

        assert user.password_hash != old_hash

    @pytest.mark.asyncio
    async def test_new_password_verifiable(self, db_session: AsyncSession) -> None:
        await _create_user(db_session)

        user = await reset_password(db_session, "admin", "NewPass@456")

        assert AuthService.verify_password("NewPass@456", user.password_hash) is True

    @pytest.mark.asyncio
    async def test_old_password_no_longer_valid(self, db_session: AsyncSession) -> None:
        user = await _create_user(db_session, password="OldPass@123")

        await reset_password(db_session, "admin", "NewPass@456")

        assert AuthService.verify_password("OldPass@123", user.password_hash) is False

    @pytest.mark.asyncio
    async def test_returns_updated_user(self, db_session: AsyncSession) -> None:
        await _create_user(db_session)

        result = await reset_password(db_session, "admin", "NewPass@456")

        assert isinstance(result, User)
        assert result.username == "admin"

    @pytest.mark.asyncio
    async def test_new_hash_is_valid_bcrypt(self, db_session: AsyncSession) -> None:
        await _create_user(db_session)

        user = await reset_password(db_session, "admin", "NewPass@456")

        # bcrypt hashes start with $2b$ and are 60 chars
        assert user.password_hash.startswith("$2b$")
        assert len(user.password_hash) == 60


# ── Session Invalidation ───────────────────────────────────────


class TestSessionInvalidation:
    """session_version must be bumped to invalidate existing sessions."""

    @pytest.mark.asyncio
    async def test_increments_session_version_from_zero(self, db_session: AsyncSession) -> None:
        await _create_user(db_session, session_version=0)

        user = await reset_password(db_session, "admin", "NewPass@456")

        assert user.session_version == 1

    @pytest.mark.asyncio
    async def test_increments_session_version_from_nonzero(self, db_session: AsyncSession) -> None:
        await _create_user(db_session, session_version=5)

        user = await reset_password(db_session, "admin", "NewPass@456")

        assert user.session_version == 6

    @pytest.mark.asyncio
    async def test_repeated_resets_keep_incrementing(self, db_session: AsyncSession) -> None:
        await _create_user(db_session, session_version=0)

        await reset_password(db_session, "admin", "NewPass@456")
        await reset_password(db_session, "admin", "AnotherP@ss1")
        user = await reset_password(db_session, "admin", "ThirdP@ss99")

        assert user.session_version == 3


# ── User Not Found ─────────────────────────────────────────────


class TestUserNotFound:
    """Nonexistent usernames must raise LookupError."""

    @pytest.mark.asyncio
    async def test_raises_for_nonexistent_user(self, db_session: AsyncSession) -> None:
        with pytest.raises(LookupError):
            await reset_password(db_session, "ghost", "NewPass@456")

    @pytest.mark.asyncio
    async def test_raises_for_empty_database(self, db_session: AsyncSession) -> None:
        with pytest.raises(LookupError):
            await reset_password(db_session, "admin", "NewPass@456")

    @pytest.mark.asyncio
    async def test_case_sensitive_username(self, db_session: AsyncSession) -> None:
        await _create_user(db_session, username="admin")

        with pytest.raises(LookupError):
            await reset_password(db_session, "Admin", "NewPass@456")

    @pytest.mark.asyncio
    async def test_username_with_leading_trailing_spaces(self, db_session: AsyncSession) -> None:
        await _create_user(db_session, username="admin")

        with pytest.raises(LookupError):
            await reset_password(db_session, " admin ", "NewPass@456")


# ── Password Policy Enforcement ────────────────────────────────


class TestPasswordPolicy:
    """Password policy validation must be enforced before any DB writes."""

    @pytest.mark.asyncio
    async def test_rejects_too_short(self, db_session: AsyncSession) -> None:
        await _create_user(db_session)

        with pytest.raises(ValueError) as exc_info:
            await reset_password(db_session, "admin", "Aa1!x")

        violations = exc_info.value.args[0]
        assert any("at least 8" in v for v in violations)

    @pytest.mark.asyncio
    async def test_rejects_too_long(self, db_session: AsyncSession) -> None:
        await _create_user(db_session)

        with pytest.raises(ValueError) as exc_info:
            await reset_password(db_session, "admin", "Aa1!" + "x" * 125)

        violations = exc_info.value.args[0]
        assert any("at most 128" in v for v in violations)

    @pytest.mark.asyncio
    async def test_rejects_no_uppercase(self, db_session: AsyncSession) -> None:
        await _create_user(db_session)

        with pytest.raises(ValueError) as exc_info:
            await reset_password(db_session, "admin", "abcdefg1!")

        violations = exc_info.value.args[0]
        assert any("uppercase" in v for v in violations)

    @pytest.mark.asyncio
    async def test_rejects_no_lowercase(self, db_session: AsyncSession) -> None:
        await _create_user(db_session)

        with pytest.raises(ValueError) as exc_info:
            await reset_password(db_session, "admin", "ABCDEFG1!")

        violations = exc_info.value.args[0]
        assert any("lowercase" in v for v in violations)

    @pytest.mark.asyncio
    async def test_rejects_no_digit(self, db_session: AsyncSession) -> None:
        await _create_user(db_session)

        with pytest.raises(ValueError) as exc_info:
            await reset_password(db_session, "admin", "Abcdefgh!")

        violations = exc_info.value.args[0]
        assert any("digit" in v for v in violations)

    @pytest.mark.asyncio
    async def test_rejects_no_special_char(self, db_session: AsyncSession) -> None:
        await _create_user(db_session)

        with pytest.raises(ValueError) as exc_info:
            await reset_password(db_session, "admin", "Abcdefg1x")

        violations = exc_info.value.args[0]
        assert any("special character" in v for v in violations)

    @pytest.mark.asyncio
    async def test_rejects_empty_password(self, db_session: AsyncSession) -> None:
        await _create_user(db_session)

        with pytest.raises(ValueError) as exc_info:
            await reset_password(db_session, "admin", "")

        violations = exc_info.value.args[0]
        assert len(violations) >= 4

    @pytest.mark.asyncio
    async def test_multiple_violations_returned(self, db_session: AsyncSession) -> None:
        await _create_user(db_session)

        with pytest.raises(ValueError) as exc_info:
            await reset_password(db_session, "admin", "abc")

        violations = exc_info.value.args[0]
        assert len(violations) >= 3  # short + no uppercase + no digit + no special

    @pytest.mark.asyncio
    async def test_invalid_password_does_not_modify_user(self, db_session: AsyncSession) -> None:
        user = await _create_user(db_session)
        old_hash = user.password_hash
        old_version = user.session_version

        with pytest.raises(ValueError):
            await reset_password(db_session, "admin", "weak")

        assert user.password_hash == old_hash
        assert user.session_version == old_version


# ── Edge Cases ─────────────────────────────────────────────────


class TestEdgeCases:
    """Edge cases: inactive users, resetting to same password, unicode, etc."""

    @pytest.mark.asyncio
    async def test_resets_inactive_user(self, db_session: AsyncSession) -> None:
        """Inactive users should still have their password reset — the admin
        may be re-enabling their account via the database."""
        await _create_user(db_session, is_active=False)

        user = await reset_password(db_session, "admin", "NewPass@456")

        assert AuthService.verify_password("NewPass@456", user.password_hash)

    @pytest.mark.asyncio
    async def test_reset_to_same_password(self, db_session: AsyncSession) -> None:
        """Resetting to the same password should still work (new bcrypt salt)."""
        password = "SamePass@123"
        user = await _create_user(db_session, password=password)
        old_hash = user.password_hash

        await reset_password(db_session, "admin", password)

        # Hash changes because bcrypt uses a new random salt.
        assert user.password_hash != old_hash
        assert AuthService.verify_password(password, user.password_hash)

    @pytest.mark.asyncio
    async def test_password_with_unicode(self, db_session: AsyncSession) -> None:
        """Unicode characters in passwords should be handled correctly."""
        await _create_user(db_session)

        user = await reset_password(db_session, "admin", "Pässwörd@1")

        assert AuthService.verify_password("Pässwörd@1", user.password_hash)

    @pytest.mark.asyncio
    async def test_password_at_exact_minimum_length(self, db_session: AsyncSession) -> None:
        await _create_user(db_session)

        user = await reset_password(db_session, "admin", "Aa1!xxxx")  # 8 chars

        assert AuthService.verify_password("Aa1!xxxx", user.password_hash)

    @pytest.mark.asyncio
    async def test_password_at_68_chars(self, db_session: AsyncSession) -> None:
        """68 chars is safely under bcrypt's 72-byte limit."""
        await _create_user(db_session)
        password = "Aa1!" + "x" * 64  # 68 chars

        user = await reset_password(db_session, "admin", password)

        assert AuthService.verify_password(password, user.password_hash)

    @pytest.mark.asyncio
    async def test_multiple_users_only_target_affected(self, db_session: AsyncSession) -> None:
        """Resetting one user must not affect another."""
        user_a = await _create_user(db_session, username="alice", password="AlicePass@1")
        user_b = await _create_user(db_session, username="bob", password="BobPass@123")
        bob_original_hash = user_b.password_hash

        await reset_password(db_session, "alice", "NewAlice@99")

        assert AuthService.verify_password("NewAlice@99", user_a.password_hash)
        assert user_b.password_hash == bob_original_hash
        assert AuthService.verify_password("BobPass@123", user_b.password_hash)

    @pytest.mark.asyncio
    async def test_password_with_all_special_chars(self, db_session: AsyncSession) -> None:
        """Various special characters should all be accepted."""
        await _create_user(db_session)

        for char in "!@#$%^&*()":
            user = await reset_password(db_session, "admin", f"TestPass1{char}")
            assert AuthService.verify_password(f"TestPass1{char}", user.password_hash)

    @pytest.mark.asyncio
    async def test_nonexistent_user_with_valid_password(self, db_session: AsyncSession) -> None:
        """Even with a valid password, nonexistent user must raise."""
        with pytest.raises(LookupError):
            await reset_password(db_session, "nobody", "ValidPass@1")

    @pytest.mark.asyncio
    async def test_flush_not_commit(self, db_session: AsyncSession) -> None:
        """reset_password() should flush (making changes visible in session)
        but not commit — letting the caller control the transaction."""
        user = await _create_user(db_session)

        await reset_password(db_session, "admin", "NewPass@456")

        # Changes are visible in the session (flushed)
        assert AuthService.verify_password("NewPass@456", user.password_hash)
        assert user.session_version == 1
