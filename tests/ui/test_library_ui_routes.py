"""Route-contract tests for the standardized library shell."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

pytest_plugins = ["conftest_security"]

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-library-ui")


@pytest.mark.asyncio
class TestLibraryRouteContracts:
    """Verify the library page renders stable shell regions."""

    async def test_library_renders_standardized_shell(
        self,
        authenticated_client,
    ) -> None:  # type: ignore[no-untyped-def]
        response = await authenticated_client.get("/library")

        assert response.status_code == 200
        assert 'data-testid="library-page"' in response.text
        assert (
            'data-testid="library-mission-control"' in response.text
            or 'data-testid="library-empty-state"' in response.text
        )
        assert 'data-testid="library-footer-strip"' in response.text

    async def test_library_renders_browser_breadcrumb_contract(
        self,
        authenticated_client,
    ) -> None:  # type: ignore[no-untyped-def]
        response = await authenticated_client.get("/library")

        assert response.status_code == 200
        if 'data-testid="library-empty-state"' not in response.text:
            assert 'data-testid="library-browser-breadcrumbs"' in response.text
            assert 'data-testid="library-browser-up"' in response.text
            assert 'data-testid="library-browser-sort-name"' in response.text
            assert 'data-testid="library-browser-sort-size"' in response.text

    async def test_library_renders_context_menu_and_modal_contracts(
        self,
        authenticated_client,
    ) -> None:  # type: ignore[no-untyped-def]
        response = await authenticated_client.get("/library")

        assert response.status_code == 200
        if 'data-testid="library-empty-state"' not in response.text:
            assert "libraryBrowserPage({" in response.text
            assert 'data-testid="library-context-menu"' in response.text
            assert 'data-testid="library-context-action-properties"' in response.text
            assert 'data-testid="library-context-action-delete"' in response.text
            assert 'data-testid="library-properties-modal"' in response.text
            assert 'data-testid="library-rename-modal"' in response.text
            assert 'data-testid="library-rename-stale-modal"' in response.text
            assert 'data-testid="library-auto-rename-modal"' in response.text
            assert 'data-testid="library-convert-modal"' in response.text
            assert 'data-testid="library-delete-file-modal"' in response.text
            assert 'data-testid="library-delete-folder-modal"' in response.text
            assert 'data-testid="library-delete-series-modal"' in response.text
            assert 'data-testid="library-rename-form"' in response.text
            assert 'data-testid="library-rename-preview-path"' in response.text
            assert 'data-testid="library-rename-action-note"' in response.text
            assert 'data-testid="library-rename-summary-row"' in response.text
            assert 'data-testid="library-rename-name-header"' in response.text
            assert 'data-testid="library-rename-name-panel"' in response.text
            assert 'data-testid="library-rename-path-header"' in response.text
            assert 'data-testid="library-rename-path-panel"' in response.text
            assert 'data-testid="library-rename-stale-reason"' in response.text
            assert 'data-testid="library-rename-stale-note"' not in response.text
            assert 'data-testid="library-rename-stale-warning-row"' in response.text
            assert 'data-testid="library-rename-stale-repair-header"' in response.text
            assert 'data-testid="library-rename-stale-repair-grid"' in response.text
            assert 'data-testid="library-auto-rename-action-note"' in response.text
            assert 'data-testid="library-auto-rename-summary-row"' in response.text
            assert 'data-testid="library-auto-rename-preview-header"' in response.text
            assert 'data-testid="library-auto-rename-preview-grid"' in response.text
            assert 'data-testid="library-convert-action-note"' in response.text
            assert 'data-testid="library-convert-summary-row"' in response.text
            assert 'data-testid="library-convert-preview-header"' in response.text
            assert 'data-testid="library-convert-preview-grid"' in response.text
            assert 'data-testid="library-convert-rows"' not in response.text
            assert 'data-testid="library-delete-file-summary"' in response.text
            assert 'data-testid="library-delete-file-warning-row"' in response.text
            assert 'data-testid="library-delete-file-impact-header"' in response.text
            assert 'data-testid="library-delete-file-impact-grid"' in response.text
            assert 'data-testid="library-delete-folder-summary"' in response.text
            assert 'data-testid="library-delete-folder-warning-row"' in response.text
            assert 'data-testid="library-delete-folder-impact-header"' in response.text
            assert 'data-testid="library-delete-folder-impact-grid"' in response.text
            assert 'data-testid="library-delete-series-summary"' in response.text
            assert 'data-testid="library-delete-series-warning-row"' in response.text
            assert 'data-testid="library-delete-series-impact-header"' in response.text
            assert 'data-testid="library-delete-series-impact-grid"' in response.text
            assert (
                "This action removes the selected file from the library path immediately."
                not in response.text
            )
            assert (
                "This action removes the selected folder from the library path immediately."
                not in response.text
            )
            assert (
                "Review the filesystem and tracking changes before deleting this file."
                not in response.text
            )
            assert (
                "Review the filesystem and tracking changes before deleting this folder."
                not in response.text
            )
            assert "Current Name" not in response.text
            assert "Preview Name" not in response.text
            assert "Queue Rename" not in response.text
            assert "Queue Convert" not in response.text
            assert "queues this convert in Utilities" not in response.text
