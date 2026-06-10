"""Route-contract tests for the matching queue UI routes."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

pytest_plugins = ["conftest_security"]

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-matching-ui")


@pytest.mark.asyncio
class TestMatchingRouteContracts:
    """Verify the matching page and HTMX partials keep stable contracts."""

    async def test_matching_queue_renders_page_shell(
        self,
        authenticated_client,
    ) -> None:  # type: ignore[no-untyped-def]
        response = await authenticated_client.get("/library/matching")

        assert response.status_code == 200
        assert 'id="matching-queue-app"' in response.text
        assert "Matching Queue" in response.text
        assert "Manual matching" in response.text
        assert "No action is needed right now." in response.text
        assert "Everything in the library is matched." in response.text

    async def test_matching_series_search_requires_a_query(
        self,
        authenticated_client,
    ) -> None:  # type: ignore[no-untyped-def]
        response = await authenticated_client.get("/htmx/matching/series")

        assert response.status_code == 200
        assert 'id="matching-queue-app"' not in response.text
        assert "No series found" not in response.text

    async def test_matching_series_search_returns_empty_result_message(
        self,
        authenticated_client,
    ) -> None:  # type: ignore[no-untyped-def]
        response = await authenticated_client.get("/htmx/matching/series?q=zz-no-series")

        assert response.status_code == 200
        assert 'id="matching-queue-app"' not in response.text
        assert 'No series found for "zz-no-series".' in response.text

    async def test_matching_issues_returns_unknown_empty_state(
        self,
        authenticated_client,
    ) -> None:  # type: ignore[no-untyped-def]
        response = await authenticated_client.get("/htmx/matching/issues?series_id=999999")

        assert response.status_code == 200
        assert 'id="matching-queue-app"' not in response.text
        assert "No issues were found for this series." in response.text
