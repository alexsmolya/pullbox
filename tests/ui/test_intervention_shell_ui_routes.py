"""Route-contract tests for the standardized intervention shell."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

pytest_plugins = ["conftest_security"]

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-intervention-shell-ui")


@pytest.mark.asyncio
class TestInterventionShellRouteContracts:
    """Verify the intervention page renders stable shell regions."""

    async def test_intervention_renders_standardized_shell(
        self,
        authenticated_client,
    ) -> None:  # type: ignore[no-untyped-def]
        response = await authenticated_client.get("/intervention")

        assert response.status_code == 200
        assert 'data-testid="intervention-page"' in response.text
        assert 'data-testid="intervention-tabs"' in response.text
        assert 'data-testid="intervention-summary-cards"' in response.text
        assert 'data-testid="intervention-results"' in response.text
        assert 'data-testid="intervention-filters"' in response.text
        assert 'data-testid="intervention-toolbar-frame"' in response.text
        assert 'data-testid="intervention-select-mode-toggle"' in response.text
        assert 'data-testid="intervention-select-toolbar"' in response.text
        assert 'data-testid="intervention-select-all-results"' in response.text
        assert 'data-testid="intervention-list"' in response.text

    async def test_intervention_list_partial_returns_list_body_only(
        self,
        authenticated_client,
    ) -> None:  # type: ignore[no-untyped-def]
        response = await authenticated_client.get("/htmx/intervention/list")

        assert response.status_code == 200
        assert (
            'data-testid="intervention-list-body"' in response.text
            or 'data-testid="intervention-empty"' in response.text
        )
        assert 'data-testid="intervention-page"' not in response.text

    async def test_intervention_hx_request_returns_page_root_bundle(
        self,
        authenticated_client,
    ) -> None:  # type: ignore[no-untyped-def]
        response = await authenticated_client.get(
            "/intervention",
            headers={"HX-Request": "true"},
        )

        assert response.status_code == 200
        assert 'data-testid="intervention-page"' in response.text
