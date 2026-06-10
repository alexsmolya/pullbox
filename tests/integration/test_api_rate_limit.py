"""Integration tests for global API rate limiting through the FastAPI middleware.

Tests verify that the RateLimitMiddleware correctly returns 429 responses
and includes rate limit headers on normal responses.

Run:
    pytest tests/integration/test_api_rate_limit.py -v
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from pullbox.models import Base
from pullbox.models.audit_log import AuditEventType
from pullbox.models.user import User
from pullbox.services.auth_service import AuthService

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-api-rate-limit")


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
    """Create a test user so setup middleware doesn't redirect."""
    async with _test_db() as session:
        user = User(
            username="testuser",
            password_hash=AuthService.hash_password("testpassword"),
        )
        session.add(user)
        await session.commit()


@pytest.fixture
async def client(
    _test_db: async_sessionmaker[AsyncSession],
    _seed_user: None,
) -> AsyncGenerator[AsyncClient, None]:
    """Create an HTTP test client with very low rate limits for testing."""
    from pullbox.api.deps import get_db_dep
    from pullbox.app import create_app

    app = create_app()

    async def _override_db() -> AsyncGenerator[AsyncSession, None]:
        async with _test_db() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db_dep] = _override_db

    # Override the rate limiter in the middleware with a very low limit
    from pullbox.core.api_rate_limiter import APIRateLimiter

    test_limiter = APIRateLimiter(tier1=2, tier2=3, tier3=5, enabled=True)

    # Find the RateLimitMiddleware in the middleware stack and replace its limiter
    from pullbox.api.middleware import RateLimitMiddleware

    for middleware in app.user_middleware:
        middleware_cls: Any = middleware.cls
        if middleware_cls is RateLimitMiddleware:
            middleware.kwargs["limiter"] = test_limiter
            break

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


# ── Tests ──────────────────────────────────────────────────────────


class TestAPIRateLimitIntegration:
    """Integration tests for global API rate limiting through HTTP."""

    @pytest.mark.asyncio
    async def test_rate_limit_returns_429_with_correct_body(self, client: AsyncClient) -> None:
        # Exhaust tier3 limit (5 GET requests)
        for _ in range(5):
            resp = await client.get("/ping")
            assert resp.status_code == 200

        # /ping is exempt, so use an API endpoint to exhaust tier3
        for _ in range(5):
            resp = await client.get(
                "/api/v1/auth/apikeys",
                headers={"accept": "application/json"},
            )
            # 401 is expected (no auth), but it still counts against rate limit
            assert resp.status_code in (200, 401)

        # 6th request should be rate limited
        resp = await client.get(
            "/api/v1/auth/apikeys",
            headers={"accept": "application/json"},
        )
        assert resp.status_code == 429

        body = resp.json()
        assert body["error"]["code"] == "RATE_LIMITED"
        assert "Retry-After" in resp.headers
        assert resp.headers["Retry-After"] == "60"

    @pytest.mark.asyncio
    async def test_rate_limit_headers_on_normal_response(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/auth/apikeys",
            headers={"accept": "application/json"},
        )
        # Even though auth fails, rate limit headers should be present
        assert "X-RateLimit-Limit" in resp.headers
        assert "X-RateLimit-Remaining" in resp.headers
        assert int(resp.headers["X-RateLimit-Limit"]) > 0

    @pytest.mark.asyncio
    async def test_hx_request_header_does_not_bypass_rate_limit(self, client: AsyncClient) -> None:
        headers = {
            "accept": "application/json",
            "HX-Request": "true",
        }

        for _ in range(5):
            resp = await client.get("/api/v1/auth/apikeys", headers=headers)
            assert resp.status_code == 401

        resp = await client.get("/api/v1/auth/apikeys", headers=headers)
        assert resp.status_code == 429

    @pytest.mark.asyncio
    async def test_api_rate_limit_is_audited(self, client: AsyncClient) -> None:
        audit_event = AsyncMock()

        with patch("pullbox.services.audit_service.audit_event", audit_event):
            for _ in range(5):
                resp = await client.get(
                    "/api/v1/auth/apikeys",
                    headers={"accept": "application/json"},
                )
                assert resp.status_code == 401

            resp = await client.get(
                "/api/v1/auth/apikeys",
                headers={"accept": "application/json"},
            )

        assert resp.status_code == 429
        audit_event.assert_awaited_once_with(
            AuditEventType.API_RATE_LIMITED,
            source_ip="127.0.0.1",
            detail="API rate limit exceeded: GET /api/v1/auth/apikeys",
        )
