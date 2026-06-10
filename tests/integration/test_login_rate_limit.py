"""Integration tests for login rate limiting via the actual FastAPI app.

Tests verify that the rate limiter is wired correctly into the login
endpoint and responds with appropriate HTTP status codes.

Run:
    pytest tests/integration/test_login_rate_limit.py -v
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from pullbox.api.v1 import auth as auth_module
from pullbox.core.rate_limiter import LoginRateLimiter
from pullbox.models import Base
from pullbox.models.audit_log import AuditEventType
from pullbox.models.user import User
from pullbox.services.audit_service import AuditService
from pullbox.services.auth_service import AuthService

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

# Ensure a secret key is set for tests
os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-rate-limit-tests")


@pytest.fixture
async def _test_db() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    """Create an in-memory database with all tables."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
async def _seed_user(_test_db: async_sessionmaker[AsyncSession]) -> None:
    """Create a test user with known credentials."""
    async with _test_db() as session:
        user = User(
            username="testuser",
            password_hash=AuthService.hash_password("correctpassword"),
        )
        session.add(user)
        await session.commit()


@pytest.fixture
async def client(
    _test_db: async_sessionmaker[AsyncSession],
    _seed_user: None,
) -> AsyncGenerator[AsyncClient, None]:
    """Create an HTTP test client with the full FastAPI app and a fresh rate limiter."""
    from pullbox.api.deps import get_db_dep
    from pullbox.app import create_app

    app = create_app()

    # Override the DB dependency to use our test database
    async def _override_db() -> AsyncGenerator[AsyncSession, None]:
        async with _test_db() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db_dep] = _override_db

    # Install a fresh rate limiter for each test so state doesn't bleed
    fresh_limiter = LoginRateLimiter(max_attempts=5)
    auth_module._rate_limiter = fresh_limiter

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac

    # Restore the default rate limiter
    auth_module._rate_limiter = LoginRateLimiter()


# ── Tests ──────────────────────────────────────────────────────────


class TestLoginRateLimitIntegration:
    """Integration tests for login rate limiting through the HTTP API."""

    @pytest.mark.asyncio
    async def test_login_rate_limit_blocks_after_failures(self, client: AsyncClient) -> None:
        # Send 5 bad logins
        for i in range(5):
            resp = await client.post(
                "/api/v1/auth/login",
                json={"username": "testuser", "password": f"wrong{i}"},
            )
            assert resp.status_code == 401, f"Request {i + 1} should be 401"

        # 6th request should be blocked by rate limiter
        resp = await client.post(
            "/api/v1/auth/login",
            json={"username": "testuser", "password": "wrong5"},
        )
        assert resp.status_code == 429
        retry_after = int(resp.headers["Retry-After"])
        assert 890 <= retry_after <= 900
        body = resp.json()
        assert body["error"]["code"] == "LOGIN_RATE_LIMITED"
        assert "Too many login attempts" in body["error"]["message"]

    @pytest.mark.asyncio
    async def test_rate_limited_login_is_audited(
        self,
        client: AsyncClient,
    ) -> None:
        original_log = AuditService.log_event
        calls: list[tuple[AuditEventType, dict[str, object]]] = []

        async def _tracking_log(
            session: object,
            event_type: AuditEventType,
            **kwargs: object,
        ) -> object:
            calls.append((event_type, kwargs))
            return await original_log(session, event_type, **kwargs)  # type: ignore[arg-type]

        for i in range(5):
            resp = await client.post(
                "/api/v1/auth/login",
                json={"username": "testuser", "password": f"wrong{i}"},
            )
            assert resp.status_code == 401

        with patch(
            "pullbox.services.audit_service.AuditService.log_event",
            side_effect=_tracking_log,
        ):
            resp = await client.post(
                "/api/v1/auth/login",
                json={"username": "testuser", "password": "wrong5"},
            )
        assert resp.status_code == 429

        rate_limited_calls = [
            call for call in calls if call[0] == AuditEventType.LOGIN_RATE_LIMITED
        ]
        assert len(rate_limited_calls) == 1
        detail = rate_limited_calls[0][1]
        assert detail["username"] == "testuser"
        assert detail["source_ip"] == "127.0.0.1"
        assert "Rate-limited login attempt" in str(detail["detail"])

    @pytest.mark.asyncio
    async def test_successful_login_resets_rate_limit(self, client: AsyncClient) -> None:
        # Send 3 bad logins
        for _ in range(3):
            resp = await client.post(
                "/api/v1/auth/login",
                json={"username": "testuser", "password": "wrongpass"},
            )
            assert resp.status_code == 401

        # Successful login resets the counter
        resp = await client.post(
            "/api/v1/auth/login",
            json={"username": "testuser", "password": "correctpassword"},
        )
        assert resp.status_code == 200

        # 3 more bad logins should NOT trigger lockout (counter was reset)
        for _ in range(3):
            resp = await client.post(
                "/api/v1/auth/login",
                json={"username": "testuser", "password": "wrongpass"},
            )
            assert resp.status_code == 401

        # Still not locked out (only 3 failures since reset)
        body = resp.json()
        assert "Too many login attempts" not in body["error"]["message"]

    @pytest.mark.asyncio
    async def test_rate_limit_per_ip(self, client: AsyncClient) -> None:
        # Exhaust attempts from default testserver IP (127.0.0.1)
        for _ in range(5):
            resp = await client.post(
                "/api/v1/auth/login",
                json={"username": "testuser", "password": "wrongpass"},
            )
            assert resp.status_code == 401

        # Default IP should be locked
        resp = await client.post(
            "/api/v1/auth/login",
            json={"username": "testuser", "password": "wrongpass"},
        )
        assert resp.status_code == 429
        assert "Too many login attempts" in resp.json()["error"]["message"]

        # A different IP should still work (gets auth error, not rate limit)
        # We can test this by checking the rate limiter directly since
        # httpx ASGI transport always uses 127.0.0.1
        fresh_limiter = auth_module._rate_limiter
        await fresh_limiter.check_rate_limit("192.168.1.100")
