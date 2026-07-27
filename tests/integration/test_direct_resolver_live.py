"""Environment-gated smoke test for a live FlareSolverr-compatible service."""

from __future__ import annotations

import os

import pytest

from pullbox.providers.direct.resolver import DirectResolverClient

BASE_URL = os.environ.get("PULLBOX_DIRECT_RESOLVER_URL")
TARGET_URL = os.environ.get("PULLBOX_DIRECT_RESOLVER_TARGET", "https://example.com/")

pytestmark = pytest.mark.skipif(
    not BASE_URL,
    reason="live direct resolver endpoint is not configured",
)


async def test_standard_v1_request_get_against_live_resolver() -> None:
    assert BASE_URL is not None
    async with DirectResolverClient(
        endpoint=BASE_URL,
        allow_private_http=BASE_URL.startswith("http://"),
        timeout_seconds=90,
    ) as client:
        result = await client.solve(
            TARGET_URL,
            declared_domains=("example.com",),
            challenge_category="compatibility_smoke",
        )

    assert result.status_code == 200
    assert "Example Domain" in result.html
    assert result.final_url.startswith("https://example.com")
