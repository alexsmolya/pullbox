"""Integration tests for password and username validation in AuthService.

Tests that password_policy enforcement works end-to-end through
AuthService.create_user() with a real async database session.

Run:
    pytest tests/integration/test_password_validation.py -v
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pullbox.core.exceptions import ValidationError
from pullbox.services.auth_service import AuthService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class TestCreateUserPasswordValidation:
    """Password policy enforced during user creation."""

    @pytest.mark.asyncio
    async def test_rejects_weak_password(self, db_session: AsyncSession) -> None:
        with pytest.raises(ValidationError, match="uppercase"):
            await AuthService.create_user(db_session, "testuser", "short1!")

    @pytest.mark.asyncio
    async def test_rejects_no_special_char(self, db_session: AsyncSession) -> None:
        with pytest.raises(ValidationError, match="special character"):
            await AuthService.create_user(db_session, "testuser", "Abcdefg1x")

    @pytest.mark.asyncio
    async def test_accepts_valid_password(self, db_session: AsyncSession) -> None:
        user = await AuthService.create_user(db_session, "testuser", "MyStr0ng!Pass")
        assert user.username == "testuser"
        assert user.password_hash != "MyStr0ng!Pass"

    @pytest.mark.asyncio
    async def test_rejects_too_long_password(self, db_session: AsyncSession) -> None:
        password = "Aa1!" + "x" * 125  # 129 chars
        with pytest.raises(ValidationError, match="at most 128"):
            await AuthService.create_user(db_session, "testuser", password)


class TestCreateUserUsernameValidation:
    """Username format enforced during user creation."""

    @pytest.mark.asyncio
    async def test_rejects_short_username(self, db_session: AsyncSession) -> None:
        with pytest.raises(ValidationError, match="at least 3"):
            await AuthService.create_user(db_session, "ab", "MyStr0ng!Pass")

    @pytest.mark.asyncio
    async def test_rejects_special_chars_in_username(self, db_session: AsyncSession) -> None:
        with pytest.raises(ValidationError, match="letters, numbers"):
            await AuthService.create_user(db_session, "user@name", "MyStr0ng!Pass")

    @pytest.mark.asyncio
    async def test_accepts_valid_username(self, db_session: AsyncSession) -> None:
        user = await AuthService.create_user(db_session, "valid_user-1", "MyStr0ng!Pass")
        assert user.username == "valid_user-1"
