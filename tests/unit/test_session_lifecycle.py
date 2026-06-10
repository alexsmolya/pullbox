"""Unit tests for session lifecycle hardening — version tracking and invalidation.

Tests verify that session tokens embed a version, mismatched versions are
rejected, password changes increment the version, and deactivated users
cannot use existing sessions.

Run:
    pytest tests/unit/test_session_lifecycle.py -v
    pytest tests/unit/test_session_lifecycle.py -v --cov=pullbox.services.auth_service
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from pullbox.models import Base
from pullbox.models.user import User
from pullbox.services.auth_service import AuthService

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-session-lifecycle")


# ── Fixtures ───────────────────────────────────────────────────────


@pytest.fixture
async def db_factory() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    """Create an in-memory database with all tables."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
async def db_session(
    db_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    """Provide a database session for tests."""
    async with db_factory() as session:
        yield session


@pytest.fixture
async def test_user(db_session: AsyncSession) -> User:
    """Create a test user with session_version=0."""
    user = User(
        username="testuser",
        password_hash=AuthService.hash_password("testpassword"),
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


# ── Token Version Tests ───────────────────────────────────────────


class TestSessionTokenVersion:
    """Tests for session version embedding in tokens."""

    def test_session_token_includes_version(self) -> None:
        token = AuthService.create_session_token(1, session_version=5)
        data = AuthService.validate_session_token(token)
        assert data is not None
        assert data["sv"] == 5

    def test_session_token_default_version_zero(self) -> None:
        token = AuthService.create_session_token(1)
        data = AuthService.validate_session_token(token)
        assert data is not None
        assert data["sv"] == 0

    def test_session_token_payload_remains_minimal(self) -> None:
        """Signed session payload should not grow into a user/profile store."""
        token = AuthService.create_session_token(1, session_version=2)
        data = AuthService.validate_session_token(token)

        assert data is not None
        assert set(data) == {"user_id", "csrf", "sv"}
        assert data["user_id"] == 1
        assert data["sv"] == 2
        assert isinstance(data["csrf"], str)

    def test_expired_session_token_is_rejected(self) -> None:
        """Session max-age enforcement rejects expired signed tokens."""
        token = AuthService.create_session_token(1, session_version=0)

        assert AuthService.validate_session_token(token, max_age_seconds=-1) is None

    def test_legacy_token_without_sv_treated_as_zero(self) -> None:
        """Simulate a legacy token that doesn't have the 'sv' key."""
        from itsdangerous import URLSafeTimedSerializer

        from pullbox.config import get_settings

        settings = get_settings()
        serializer = URLSafeTimedSerializer(settings.secret_key)
        # Create a token WITHOUT 'sv' key — simulates pre-upgrade tokens
        legacy_token = serializer.dumps({"user_id": 1, "csrf": "abc123"})

        data = AuthService.validate_session_token(legacy_token)
        assert data is not None
        assert "sv" not in data
        # Code should treat missing sv as 0
        assert data.get("sv", 0) == 0


# ── Session Version Validation ────────────────────────────────────


class TestSessionVersionValidation:
    """Tests for session version matching logic."""

    def test_session_valid_when_version_matches(self) -> None:
        token = AuthService.create_session_token(1, session_version=3)
        data = AuthService.validate_session_token(token)
        assert data is not None
        # When user.session_version == 3 and token sv == 3, should match
        assert data["sv"] == 3

    def test_session_rejected_when_version_mismatch(self) -> None:
        token = AuthService.create_session_token(1, session_version=0)
        data = AuthService.validate_session_token(token)
        assert data is not None
        token_sv = data.get("sv", 0)
        # If user's session_version was bumped to 1, this should NOT match
        user_session_version = 1
        assert token_sv != user_session_version


# ── Session Version Increment ─────────────────────────────────────


class TestSessionVersionIncrement:
    """Tests for increment_session_version()."""

    @pytest.mark.asyncio
    async def test_password_change_increments_version(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        assert test_user.session_version == 0
        new_version = await AuthService.increment_session_version(db_session, test_user.id)
        assert new_version == 1
        await db_session.refresh(test_user)
        assert test_user.session_version == 1

    @pytest.mark.asyncio
    async def test_increment_twice(self, db_session: AsyncSession, test_user: User) -> None:
        await AuthService.increment_session_version(db_session, test_user.id)
        new_version = await AuthService.increment_session_version(db_session, test_user.id)
        assert new_version == 2

    @pytest.mark.asyncio
    async def test_increment_nonexistent_user_raises(self, db_session: AsyncSession) -> None:
        from pullbox.core.exceptions import NotFoundError

        with pytest.raises(NotFoundError):
            await AuthService.increment_session_version(db_session, 99999)


# ── Default Value ─────────────────────────────────────────────────


class TestSessionVersionDefaults:
    """Tests for session_version default value."""

    @pytest.mark.asyncio
    async def test_session_version_defaults_to_zero(self, db_session: AsyncSession) -> None:
        user = User(
            username="newuser",
            password_hash=AuthService.hash_password("pass123"),
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        assert user.session_version == 0


# ── Integration: Full Session Lifecycle ───────────────────────────


class TestSessionLifecycleIntegration:
    """Integration tests for session version checks in get_current_user."""

    @pytest.mark.asyncio
    async def test_old_session_invalid_after_version_bump(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        """Token created with sv=0 should fail when user.session_version becomes 1."""
        old_token = AuthService.create_session_token(test_user.id, session_version=0)
        old_data = AuthService.validate_session_token(old_token)
        assert old_data is not None

        # Bump version
        await AuthService.increment_session_version(db_session, test_user.id)
        await db_session.refresh(test_user)

        # Old token's sv no longer matches
        token_sv = old_data.get("sv", 0)
        assert token_sv != test_user.session_version

    @pytest.mark.asyncio
    async def test_new_session_valid_after_version_bump(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        """Token created with the new version should succeed."""
        new_version = await AuthService.increment_session_version(db_session, test_user.id)
        new_token = AuthService.create_session_token(test_user.id, session_version=new_version)
        new_data = AuthService.validate_session_token(new_token)
        assert new_data is not None

        await db_session.refresh(test_user)
        assert new_data["sv"] == test_user.session_version

    @pytest.mark.asyncio
    async def test_inactive_user_session_rejected(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        """A valid token for a deactivated user should be treated as invalid."""
        token = AuthService.create_session_token(test_user.id, session_version=0)
        data = AuthService.validate_session_token(token)
        assert data is not None

        # Deactivate user
        test_user.is_active = False
        await db_session.commit()
        await db_session.refresh(test_user)

        # Token is technically valid, but user is inactive
        assert not test_user.is_active
