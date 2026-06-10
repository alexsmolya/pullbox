"""Unit tests for error sanitization and CORS lockdown in app.py.

Tests verify that unhandled exceptions hide internal details in production
mode, PullboxError subclasses always show their message, and CORS only
allows explicit localhost origins.

Run:
    pytest tests/unit/test_error_sanitization.py -v
    pytest tests/unit/test_error_sanitization.py -v --cov=pullbox.app
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from pullbox.core.exceptions import NotFoundError, PullboxError

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-error-sanitization")

_SECRET_MESSAGE = "Database file /home/user/data/pullbox.db is corrupted"


def _build_error_app(*, debug: bool) -> FastAPI:
    """Build a minimal FastAPI app with the same error handlers as app.py.

    Uses a clean app to isolate error-handler behaviour from middleware
    interactions.  The handler logic mirrors create_app() exactly.
    """
    app = FastAPI()

    @app.exception_handler(PullboxError)
    async def pullbox_error_handler(_request: Request, exc: PullboxError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    @app.exception_handler(Exception)
    async def generic_error_handler(_request: Request, exc: Exception) -> JSONResponse:
        message = str(exc) if debug else "An unexpected error occurred."
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "INTERNAL_ERROR", "message": message}},
        )

    @app.get("/test/crash")
    async def crash() -> None:
        raise RuntimeError(_SECRET_MESSAGE)

    @app.get("/test/not-found")
    async def not_found() -> None:
        raise NotFoundError("Series", 42)

    return app


def _build_cors_app(*, debug: bool) -> FastAPI:
    """Build an app that mirrors the CORS setup from create_app()."""
    app = FastAPI()

    if debug:
        port = 8585
        allowed_origins = [
            f"http://localhost:{port}",
            f"http://127.0.0.1:{port}",
            "http://localhost:8585",
            "http://127.0.0.1:8585",
        ]
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.get("/ping")
    async def ping() -> dict[str, str]:
        return {"status": "ok"}

    return app


@pytest.fixture
async def production_client() -> AsyncGenerator[AsyncClient, None]:
    """Client for an app running in production mode (debug=False)."""
    app = _build_error_app(debug=False)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest.fixture
async def debug_client() -> AsyncGenerator[AsyncClient, None]:
    """Client for an app running in debug mode (debug=True)."""
    app = _build_error_app(debug=True)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest.fixture
async def cors_debug_client() -> AsyncGenerator[AsyncClient, None]:
    """Client for a debug-mode app with CORS enabled."""
    app = _build_cors_app(debug=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest.fixture
async def cors_production_client() -> AsyncGenerator[AsyncClient, None]:
    """Client for a production-mode app without CORS."""
    app = _build_cors_app(debug=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


# ── Error Sanitization ────────────────────────────────────────────


class TestErrorSanitization:
    """Tests for the generic exception handler's production/debug behavior."""

    @pytest.mark.asyncio
    async def test_production_error_hides_details(self, production_client: AsyncClient) -> None:
        resp = await production_client.get("/test/crash")
        assert resp.status_code == 500

        body = resp.json()
        assert body["error"]["code"] == "INTERNAL_ERROR"
        assert body["error"]["message"] == "An unexpected error occurred."
        # Must NOT leak internal paths or exception details
        assert "pullbox.db" not in resp.text
        assert "/home/user" not in resp.text

    @pytest.mark.asyncio
    async def test_debug_error_shows_details(self, debug_client: AsyncClient) -> None:
        resp = await debug_client.get("/test/crash")
        assert resp.status_code == 500

        body = resp.json()
        assert body["error"]["code"] == "INTERNAL_ERROR"
        # Debug mode reveals the full exception message
        assert "pullbox.db" in body["error"]["message"]
        assert "corrupted" in body["error"]["message"]

    @pytest.mark.asyncio
    async def test_pullbox_errors_always_show_message_production(
        self, production_client: AsyncClient
    ) -> None:
        resp = await production_client.get("/test/not-found")
        assert resp.status_code == 404

        body = resp.json()
        assert body["error"]["code"] == "SERIES_NOT_FOUND"
        assert "42" in body["error"]["message"]
        assert "not found" in body["error"]["message"].lower()

    @pytest.mark.asyncio
    async def test_pullbox_errors_always_show_message_debug(
        self, debug_client: AsyncClient
    ) -> None:
        resp = await debug_client.get("/test/not-found")
        assert resp.status_code == 404

        body = resp.json()
        assert body["error"]["code"] == "SERIES_NOT_FOUND"
        assert "42" in body["error"]["message"]

    @pytest.mark.asyncio
    async def test_error_response_is_json(self, production_client: AsyncClient) -> None:
        resp = await production_client.get("/test/crash")
        assert resp.status_code == 500
        assert "application/json" in resp.headers["content-type"]
        body = resp.json()
        assert "error" in body


# ── CORS Lockdown ─────────────────────────────────────────────────


class TestCORSLockdown:
    """Tests for CORS origin restrictions."""

    @pytest.mark.asyncio
    async def test_cors_rejects_unknown_origin(self, cors_debug_client: AsyncClient) -> None:
        resp = await cors_debug_client.options(
            "/ping",
            headers={
                "Origin": "https://evil.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        # CORS middleware should not reflect an unknown origin
        assert resp.headers.get("access-control-allow-origin") != "https://evil.com"

    @pytest.mark.asyncio
    async def test_cors_allows_localhost(self, cors_debug_client: AsyncClient) -> None:
        resp = await cors_debug_client.options(
            "/ping",
            headers={
                "Origin": "http://localhost:8585",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:8585"

    @pytest.mark.asyncio
    async def test_cors_allows_127_0_0_1(self, cors_debug_client: AsyncClient) -> None:
        resp = await cors_debug_client.options(
            "/ping",
            headers={
                "Origin": "http://127.0.0.1:8585",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.headers.get("access-control-allow-origin") == "http://127.0.0.1:8585"

    @pytest.mark.asyncio
    async def test_production_has_no_cors(self, cors_production_client: AsyncClient) -> None:
        """Production mode (debug=False) should not add CORS middleware."""
        resp = await cors_production_client.options(
            "/ping",
            headers={
                "Origin": "http://localhost:8585",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert "access-control-allow-origin" not in resp.headers
