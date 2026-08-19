"""Route-contract tests for the rewritten health shell."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

pytest_plugins = ["conftest_security"]

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-health-ui")


@pytest.mark.asyncio
class TestHealthRouteContracts:
    """Verify the health area renders a stable mounted shell."""

    async def test_health_renders_standardized_shell(
        self,
        authenticated_client,
    ) -> None:  # type: ignore[no-untyped-def]
        response = await authenticated_client.get("/health")

        assert response.status_code == 200
        assert 'data-testid="health-page"' in response.text
        assert 'data-testid="health-mission-control"' in response.text
        assert 'data-testid="health-refresh-button"' in response.text
        assert 'data-testid="health-scoreboard"' in response.text
        assert 'data-testid="health-component-registry"' in response.text
        assert 'data-testid="health-footer-dock"' in response.text
        assert 'data-testid="health-footer-strip"' not in response.text
        assert 'data-testid="health-status-region"' in response.text
        assert "healthPage(" in response.text
        assert 'data-testid="health-component-card-database"' in response.text
        assert 'href="/health/database"' in response.text
        assert 'data-testid="health-component-detail-page"' not in response.text
        assert 'data-testid="health-header"' not in response.text
        assert 'data-testid="health-body"' not in response.text
        assert 'data-testid="health-toolbar"' not in response.text

    async def test_health_status_partial_returns_mounted_region(
        self,
        authenticated_client,
    ) -> None:  # type: ignore[no-untyped-def]
        response = await authenticated_client.get(
            "/health/status",
            headers={"HX-Request": "true"},
        )

        assert response.status_code == 200
        assert 'data-testid="health-status-region"' in response.text
        assert 'x-data="healthPage(' in response.text
        assert 'data-testid="health-page"' not in response.text

    async def test_health_component_page_renders_detail_route(
        self,
        authenticated_client,
    ) -> None:  # type: ignore[no-untyped-def]
        response = await authenticated_client.get("/health/database")

        assert response.status_code == 200
        assert 'data-testid="health-component-page"' in response.text
        assert 'data-testid="health-component-status-region"' in response.text
        assert 'data-testid="health-component-detail-page"' in response.text
        assert 'data-testid="health-component-detail-database"' in response.text
        assert 'data-testid="health-detail-back-link"' in response.text
        assert 'data-testid="health-detail-optimize-database-link"' in response.text
        assert 'href="/utilities/db-check?check=optimize"' in response.text
        assert 'data-testid="health-component-footer-dock"' in response.text
        assert 'data-testid="health-history-toolbar"' in response.text
        assert 'data-testid="health-history-search-field"' in response.text
        assert 'id="health-history-results"' in response.text
        assert 'data-testid="health-history-results"' in response.text
        assert 'hx-target="#health-history-results"' in response.text
        assert 'hx-select="#health-history-results"' in response.text
        assert 'data-testid="health-history-sort-checked_at"' in response.text
        assert 'href="/health"' in response.text

    async def test_download_clients_page_renders_registry_route(
        self,
        authenticated_client,
    ) -> None:  # type: ignore[no-untyped-def]
        response = await authenticated_client.get("/health/download_clients")

        assert response.status_code == 200
        assert 'data-testid="health-download-clients-page"' in response.text
        assert 'data-testid="health-download-clients-status-region"' in response.text
        assert 'data-testid="health-download-clients-detail-page"' in response.text
        assert 'data-testid="health-download-clients-table"' in response.text
        assert 'data-testid="health-download-clients-footer-dock"' in response.text
        assert "downloads-action-group is-hover-reveal" not in response.text
        assert 'data-testid="health-history-toolbar"' not in response.text

    async def test_indexers_page_renders_registry_route(
        self,
        authenticated_client,
    ) -> None:  # type: ignore[no-untyped-def]
        response = await authenticated_client.get("/health/indexers")

        assert response.status_code == 200
        assert 'data-testid="health-indexers-page"' in response.text
        assert 'data-testid="health-indexers-status-region"' in response.text
        assert 'data-testid="health-indexers-detail-page"' in response.text
        assert 'data-testid="health-proxies-table"' in response.text
        assert 'data-testid="health-indexers-table"' in response.text
        assert 'data-testid="health-indexers-footer-dock"' in response.text
        assert 'data-testid="health-history-toolbar"' not in response.text

    async def test_health_component_partial_returns_region_and_footer_bundle(
        self,
        authenticated_client,
    ) -> None:  # type: ignore[no-untyped-def]
        response = await authenticated_client.get(
            "/health/database/status",
            headers={"HX-Request": "true"},
        )

        assert response.status_code == 200
        assert 'data-testid="health-component-status-region"' in response.text
        assert 'x-data="healthPage(' in response.text
        assert 'data-testid="health-component-detail-page"' in response.text
        assert 'data-testid="health-component-page"' not in response.text
        assert 'id="page-footer-dock"' in response.text
        assert 'hx-swap-oob="innerHTML"' in response.text

    async def test_download_clients_partial_returns_region_and_footer_bundle(
        self,
        authenticated_client,
    ) -> None:  # type: ignore[no-untyped-def]
        response = await authenticated_client.get(
            "/health/download_clients/status",
            headers={"HX-Request": "true"},
        )

        assert response.status_code == 200
        assert 'data-testid="health-download-clients-status-region"' in response.text
        assert 'x-data="healthPage(' in response.text
        assert 'data-testid="health-download-clients-detail-page"' in response.text
        assert 'id="page-footer-dock"' in response.text
        assert 'hx-swap-oob="innerHTML"' in response.text

    async def test_indexers_partial_returns_region_and_footer_bundle(
        self,
        authenticated_client,
    ) -> None:  # type: ignore[no-untyped-def]
        response = await authenticated_client.get(
            "/health/indexers/status",
            headers={"HX-Request": "true"},
        )

        assert response.status_code == 200
        assert 'data-testid="health-indexers-status-region"' in response.text
        assert 'x-data="healthPage(' in response.text
        assert 'data-testid="health-indexers-detail-page"' in response.text
        assert 'id="page-footer-dock"' in response.text
        assert 'hx-swap-oob="innerHTML"' in response.text
