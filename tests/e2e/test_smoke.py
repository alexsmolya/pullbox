"""
Smoke tests — minimal validation for a running Pullbox instance.

These tests run against the actual Docker container in docker.yml.
They verify the image boots, serves pages, and passes basic checks
without testing deep functionality.

When PULLBOX_SMOKE_TEST is set, tests use --base-url from the CLI
(external container). Otherwise they use the live_server fixture.

Run:
    pytest tests/e2e/test_smoke.py -v --browser chromium

Against Docker container:
    PULLBOX_SMOKE_TEST=true pytest tests/e2e/test_smoke.py -v --base-url http://localhost:8585
"""

from __future__ import annotations

import os

import httpx
import pytest

pytestmark = pytest.mark.e2e


@pytest.fixture()
def smoke_url(request: pytest.FixtureRequest) -> str:
    """Use --base-url or PULLBOX_SMOKE_URL when running against an external container.

    In docker.yml smoke tests, PULLBOX_SMOKE_TEST=true and --base-url point to
    the container. In local development, the live_server fixture boots a server.
    """
    external = os.environ.get("PULLBOX_SMOKE_URL") or os.environ.get("PULLBOX_SMOKE_TEST")
    if external:
        # Running against an external container — use --base-url from CLI
        return os.environ.get(
            "PULLBOX_SMOKE_URL",
            request.config.getoption("--base-url", default="http://localhost:8585"),
        )
    # Local development — boot a server via the live_server fixture
    return request.getfixturevalue("live_server")


class TestSmoke:
    """Minimal smoke tests — validates a running Pullbox instance boots correctly."""

    def test_ping_returns_ok(self, smoke_url: str) -> None:
        """GET /ping returns 200 with expected JSON payload."""
        resp = httpx.get(f"{smoke_url}/ping", timeout=5.0)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "pullbox"

    def test_setup_wizard_or_login_loads(self, smoke_url: str) -> None:
        """Root URL redirects to setup or login (not a 500)."""
        resp = httpx.get(smoke_url, timeout=5.0, follow_redirects=True)
        # Fresh instance: 302 → /setup (HTML) or 403 (API/non-browser)
        # Already set up: 302 → /login
        # All acceptable — only 500 is a failure
        assert resp.status_code != 500
        # Verify the redirect target makes sense
        url_path = str(resp.url)
        is_expected = any(p in url_path for p in ("/setup", "/login")) or resp.status_code in (
            401,
            403,
        )
        assert is_expected, f"Unexpected: {resp.status_code} at {resp.url}"

    def test_static_css_loads(self, smoke_url: str) -> None:
        """Static CSS file returns 200 (not missing from Docker build)."""
        resp = httpx.get(f"{smoke_url}/static/css/tailwind.css", timeout=5.0)
        assert resp.status_code == 200
        assert "text/css" in resp.headers.get("content-type", "")

    def test_static_js_loads(self, smoke_url: str) -> None:
        """Static JS files return 200."""
        resp = httpx.get(f"{smoke_url}/static/js/htmx.min.js", timeout=5.0)
        assert resp.status_code == 200

    def test_health_endpoint_responds(self, smoke_url: str) -> None:
        """/api/v1/health returns 200, 401 (auth required), or 503 — never 500."""
        resp = httpx.get(f"{smoke_url}/api/v1/health", timeout=10.0)
        # 200 = healthy, 401 = auth required (expected), 503 = degraded
        assert resp.status_code in (200, 401, 503)
        data = resp.json()
        # Authenticated response has "status", unauthenticated has "error"
        assert "status" in data or "error" in data

    def test_openapi_docs_load(self, smoke_url: str) -> None:
        """/docs (Swagger UI) returns 200."""
        resp = httpx.get(f"{smoke_url}/docs", timeout=5.0)
        assert resp.status_code == 200

    def test_openapi_schema_loads(self, smoke_url: str) -> None:
        """/openapi.json returns valid JSON with paths."""
        resp = httpx.get(f"{smoke_url}/openapi.json", timeout=5.0)
        assert resp.status_code == 200
        data = resp.json()
        assert "paths" in data
        assert "info" in data
