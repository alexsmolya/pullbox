"""Route-contract tests for the rewritten blocklist shell."""

from __future__ import annotations

import os
import sys

import pytest
from sqlalchemy import select

from pullbox.models.blocklist import BlocklistEntry, BlocklistReason, normalize_release_title

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

pytest_plugins = ["conftest_security"]

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-blocklist-ui")


async def _seed_blocklist_error_contract_data(sec_db) -> int:  # type: ignore[no-untyped-def]
    """Seed one blocklist row with a heavy error detail for lazy-load coverage."""
    release_title = "Batman 999 (2026) [Digital] Team-DCP"
    async with sec_db() as session:
        entry = BlocklistEntry(
            release_title=release_title,
            release_title_normalized=normalize_release_title(release_title),
            reason=BlocklistReason.FAILED,
            error_message="Blocklist contract failure detail that should load lazily.",
            release_group="Team-DCP",
        )
        session.add(entry)
        await session.commit()
        return entry.id


@pytest.mark.asyncio
class TestBlocklistRouteContracts:
    """Verify the blocklist page renders stable mounted regions."""

    async def test_blocklist_renders_standardized_shell(
        self,
        authenticated_client,
    ) -> None:  # type: ignore[no-untyped-def]
        response = await authenticated_client.get("/blocklist")

        assert response.status_code == 200
        assert 'data-testid="blocklist-page"' in response.text
        assert 'data-testid="blocklist-content"' in response.text
        assert 'data-testid="blocklist-header"' in response.text
        assert 'data-testid="blocklist-header-metrics"' in response.text
        assert 'data-testid="blocklist-gauges"' in response.text
        assert 'data-testid="blocklist-results"' in response.text
        assert 'class="downloads-table-wrap"' in response.text
        assert 'data-testid="page-footer-dock"' in response.text
        assert 'data-testid="page-dock-inner"' in response.text
        assert 'data-testid="page-dock-status"' in response.text
        assert 'data-testid="blocklist-filters"' in response.text
        assert 'data-testid="blocklist-filter-form"' in response.text
        assert 'data-testid="blocklist-results-body"' in response.text
        assert 'data-testid="blocklist-search-field"' in response.text
        assert 'data-testid="blocklist-search-input"' in response.text
        assert 'data-testid="blocklist-search-clear"' in response.text
        assert 'data-testid="blocklist-search-history-panel"' in response.text
        assert 'data-search-field-contract="baseline-v2"' in response.text
        assert 'data-search-field-mode="remote"' in response.text
        assert 'data-search-field-debounce="250"' in response.text
        assert 'data-search-history-key="pullbox.searchHistory.blocklist"' in response.text
        assert 'oninput="syncSearchFieldState(this); handleSearchFieldInput(this)"' in response.text
        assert 'x-model="value"' not in response.text
        assert 'x-show="value.length > 0"' not in response.text
        assert 'data-testid="blocklist-filter-reason"' in response.text
        assert 'data-dropdown-select-contract="v1"' in response.text
        assert '<select name="reason"' not in response.text
        assert 'id="blocklist-clear-slot"' in response.text
        assert (
            'data-testid="blocklist-table"' in response.text
            or 'data-testid="blocklist-empty"' in response.text
        )

    async def test_blocklist_hx_filter_returns_bundle(
        self,
        authenticated_client,
    ) -> None:  # type: ignore[no-untyped-def]
        response = await authenticated_client.get(
            "/blocklist?reason=failed",
            headers={"HX-Request": "true"},
        )

        assert response.status_code == 200
        assert 'id="blocklist-header-metrics"' in response.text
        assert 'id="page-footer-dock"' in response.text
        assert 'hx-swap-oob="outerHTML"' in response.text
        assert 'data-testid="blocklist-results-body"' in response.text
        assert 'data-testid="blocklist-results"' not in response.text
        assert 'data-testid="blocklist-filters"' not in response.text
        assert 'data-testid="blocklist-page"' not in response.text

    async def test_blocklist_partial_returns_results_only(
        self,
        authenticated_client,
    ) -> None:  # type: ignore[no-untyped-def]
        response = await authenticated_client.get(
            "/htmx/blocklist",
            headers={"HX-Request": "true"},
        )

        assert response.status_code == 200
        assert 'data-testid="blocklist-results-body"' in response.text
        assert 'data-testid="blocklist-results"' not in response.text
        assert 'data-testid="blocklist-filters"' not in response.text
        assert 'data-testid="blocklist-page"' not in response.text

    async def test_blocklist_results_lazy_load_error_details(
        self,
        authenticated_client,
        sec_db,
    ) -> None:  # type: ignore[no-untyped-def]
        entry_id = await _seed_blocklist_error_contract_data(sec_db)

        response = await authenticated_client.get(
            "/htmx/blocklist",
            headers={"HX-Request": "true"},
        )

        assert response.status_code == 200
        assert 'data-testid="blocklist-table"' in response.text
        assert f'hx-get="/htmx/blocklist/{entry_id}/error-detail"' in response.text
        assert 'data-testid="blocklist-error-detail-content"' not in response.text
        assert 'id="blocklist-error-row-' not in response.text
        assert "Blocklist contract failure detail that should load lazily." not in response.text

    async def test_blocklist_error_detail_loads_only_on_expand(
        self,
        authenticated_client,
        sec_db,
    ) -> None:  # type: ignore[no-untyped-def]
        await _seed_blocklist_error_contract_data(sec_db)

        async with sec_db() as session:
            entry_id = (
                await session.execute(
                    select(BlocklistEntry.id).where(
                        BlocklistEntry.error_message
                        == "Blocklist contract failure detail that should load lazily."
                    )
                )
            ).scalar_one()

        response = await authenticated_client.get(
            f"/htmx/blocklist/{entry_id}/error-detail",
            headers={"HX-Request": "true"},
        )

        assert response.status_code == 200
        assert f'id="blocklist-error-row-{entry_id}"' in response.text
        assert 'data-testid="blocklist-error-detail-content"' in response.text
        assert "Blocklist contract failure detail that should load lazily." in response.text
