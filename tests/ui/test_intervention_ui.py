"""Tests for the Intervention Queue UI page — ESM Phase 2, Task 2.5.

Covers:
- GET /intervention returns 200 with HTML page
- Empty queue shows "No pending matches" message
- POST /htmx/intervention/{id}/approve returns success partial
- POST /htmx/intervention/{id}/reject returns dismissed partial
- Queue list with pending matches renders cards
- Count badge endpoint returns HTML fragment

Run:
    pytest tests/ui/test_intervention_ui.py -v
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from pullbox.models import Base
from pullbox.models.issue import Issue, IssueStatus, IssueType
from pullbox.models.pending_match import PendingMatch, PendingMatchStatus
from pullbox.models.series import Series, SeriesStatus, SeriesType
from pullbox.models.user import APIKey, User
from pullbox.services.auth_service import AuthService

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-intervention-ui")


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
async def _db_factory() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
async def _api_key_header(
    _db_factory: async_sessionmaker[AsyncSession],
) -> str:
    """Create a test user + API key, return the raw key string."""
    raw_key = "pb_k1_" + "b" * 64
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    async with _db_factory() as session:
        user = User(
            username="interventionuiuser",
            password_hash=AuthService.hash_password("Test@1234"),
        )
        session.add(user)
        await session.flush()
        session.add(APIKey(user_id=user.id, key_hash=key_hash, name="intervention-ui-test"))
        await session.commit()
    return raw_key


@pytest.fixture
async def client(
    _db_factory: async_sessionmaker[AsyncSession],
    _api_key_header: str,
) -> AsyncGenerator[AsyncClient, None]:
    """HTTP client authenticated via API key."""
    from pullbox.api.deps import get_db_dep
    from pullbox.api.middleware import reset_setup_cache
    from pullbox.app import create_app

    app = create_app()
    # Keep setup/auth middleware on the same in-memory database as the route deps.
    app.state.db_session_factory = _db_factory

    async def _override_db() -> AsyncGenerator[AsyncSession, None]:
        async with _db_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db_dep] = _override_db
    reset_setup_cache()

    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"X-Api-Key": _api_key_header},
    ) as ac:
        yield ac

    app.dependency_overrides.clear()
    reset_setup_cache()


async def _seed_pending_matches(
    factory: async_sessionmaker[AsyncSession],
    *,
    count: int = 3,
) -> list[int]:
    """Seed a series, issue, and pending matches. Returns list of pending match IDs."""
    async with factory() as session:
        series = Series(
            comicvine_id=99900,
            title="Batman",
            sort_title="Batman",
            year_start=2016,
            status=SeriesStatus.CONTINUING,
            series_type=SeriesType.STANDARD,
            monitored=True,
            issue_count=1,
        )
        session.add(series)
        await session.flush()

        issue = Issue(
            series_id=series.id,
            comicvine_id=50001,
            issue_number=1.0,
            title="Issue #1",
            status=IssueStatus.WANTED,
            issue_type=IssueType.ISSUE,
        )
        session.add(issue)
        await session.flush()

        pm_ids: list[int] = []
        for i in range(count):
            pm = PendingMatch(
                issue_id=issue.id,
                release_title=f"Batman 001 (2016) [Digital] Release{i}.cbz",
                download_url=f"https://indexer.example.com/dl/test{i}",
                is_torrent=False,
                file_size=100_000_000 + i * 1_000_000,
                confidence="medium",
                match_details={
                    "parsed_series": "Batman",
                    "parsed_issue": 1.0,
                    "parsed_year": 2016,
                    "series_similarity": 0.95,
                    "issue_match": True,
                    "year_match": True,
                    "type_match": True,
                    "indexer_name": "NZBgeek",
                    "age_days": 2,
                },
                status=PendingMatchStatus.PENDING,
            )
            session.add(pm)
            await session.flush()
            pm_ids.append(pm.id)

        await session.commit()
        return pm_ids


async def _seed_intervention_history(
    factory: async_sessionmaker[AsyncSession],
) -> list[int]:
    """Seed resolved intervention entries for history-tab coverage."""
    async with factory() as session:
        series = Series(
            comicvine_id=99901,
            title="Saga",
            sort_title="Saga",
            year_start=2012,
            status=SeriesStatus.CONTINUING,
            series_type=SeriesType.STANDARD,
            monitored=True,
            issue_count=3,
        )
        session.add(series)
        await session.flush()

        issue = Issue(
            series_id=series.id,
            comicvine_id=50002,
            issue_number=2.0,
            title="Issue #2",
            status=IssueStatus.WANTED,
            issue_type=IssueType.ISSUE,
        )
        session.add(issue)
        await session.flush()

        history_ids: list[int] = []
        rows = [
            (
                "Saga 002 (2012) [Digital] Approved.cbz",
                "high",
                False,
                PendingMatchStatus.APPROVED,
                None,
            ),
            (
                "Saga 002 (2012) [Digital] Rejected.cbz",
                "medium",
                True,
                PendingMatchStatus.REJECTED,
                "Wrong cover scan",
            ),
            (
                "Saga 002 (2012) [Digital] Expired.cbz",
                "low",
                False,
                PendingMatchStatus.EXPIRED,
                None,
            ),
        ]
        for idx, (title, confidence, is_torrent, status, rejection_reason) in enumerate(rows):
            match_details: dict[str, object] = {
                "parsed_series": "Saga",
                "parsed_issue": 2.0,
                "parsed_year": 2012,
                "series_similarity": 0.91 - (idx * 0.02),
                "series_match_type": "fuzzy" if idx < 2 else "exact",
                "issue_match": idx != 1,
                "year_match": idx != 2,
                "type_match": True,
                "indexer_name": f"Indexer {idx + 1}",
                "age_days": idx + 1,
            }
            if rejection_reason:
                match_details["rejection_reason"] = rejection_reason

            pm = PendingMatch(
                issue_id=issue.id,
                release_title=title,
                download_url=f"https://indexer.example.com/history/{idx}",
                is_torrent=is_torrent,
                file_size=90_000_000 + idx * 5_000_000,
                confidence=confidence,
                match_details=match_details,
                status=status,
            )
            session.add(pm)
            await session.flush()
            history_ids.append(pm.id)

        await session.commit()
        return history_ids


# ── Tests ──────────────────────────────────────────────────────────────


class TestInterventionUI:
    """Tests for the intervention queue UI page and HTMX endpoints."""

    @pytest.mark.asyncio
    async def test_page_renders(
        self,
        client: AsyncClient,
    ) -> None:
        """GET /intervention returns 200 with HTML containing page title."""
        resp = await client.get("/intervention")

        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        html = resp.text
        assert "Intervention Queue" in html

    @pytest.mark.asyncio
    async def test_empty_state(
        self,
        client: AsyncClient,
    ) -> None:
        """Empty queue shows 'No pending matches' message."""
        resp = await client.get("/intervention")

        assert resp.status_code == 200
        html = resp.text
        assert "No pending matches" in html

    @pytest.mark.asyncio
    async def test_htmx_approve(
        self,
        client: AsyncClient,
        _db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """POST /htmx/intervention/{id}/approve returns success partial."""
        pm_ids = await _seed_pending_matches(_db_factory, count=1)

        mock_download = MagicMock()
        mock_download.id = 42
        mock_download.issue_id = 1
        mock_download.title = "Batman 001 (2016) [Digital] Release0.cbz"
        mock_download.state = "sent"

        with (
            patch(
                "pullbox.composition.providers.build_registry",
                new_callable=AsyncMock,
                return_value=(MagicMock(), {}),
            ),
            patch(
                "pullbox.services.intervention_service.InterventionService.approve_match",
                new_callable=AsyncMock,
                return_value=mock_download,
            ),
        ):
            resp = await client.post(f"/htmx/intervention/{pm_ids[0]}/approve")

        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        html = resp.text
        assert "Approved" in html or "approved" in html

    @pytest.mark.asyncio
    async def test_htmx_reject(
        self,
        client: AsyncClient,
        _db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """POST /htmx/intervention/{id}/reject returns dismissed partial."""
        pm_ids = await _seed_pending_matches(_db_factory, count=1)

        resp = await client.post(f"/htmx/intervention/{pm_ids[0]}/reject")

        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        html = resp.text
        assert "Rejected" in html or "rejected" in html

    @pytest.mark.asyncio
    async def test_queue_list_renders_cards(
        self,
        client: AsyncClient,
        _db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """GET /htmx/intervention/list returns HTML with pending match cards."""
        await _seed_pending_matches(_db_factory, count=2)

        resp = await client.get("/htmx/intervention/list")

        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        html = resp.text
        assert "Batman 001 (2016)" in html
        assert "NZBgeek" in html

    @pytest.mark.asyncio
    async def test_count_badge(
        self,
        client: AsyncClient,
        _db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """GET /htmx/intervention/count returns badge HTML with count."""
        await _seed_pending_matches(_db_factory, count=3)

        resp = await client.get("/htmx/intervention/count")

        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        html = resp.text
        assert "3" in html


# ── Direct handler unit tests (coverage supplement) ───────────────────


def _mock_request() -> MagicMock:
    """Build a mock Starlette Request good enough for _ctx() and templates."""
    req = MagicMock(spec=["state", "url", "base_url", "headers", "query_params"])
    req.state = MagicMock()
    req.state.csrf_token = "fake-csrf"
    req.url = MagicMock()
    req.url.path = "/intervention"
    req.base_url = "http://testserver/"
    req.headers = {}
    req.query_params = {}
    return req


class TestHandlersDirect:
    """Direct handler tests for UI intervention routes — bypasses ASGI transport."""

    @pytest.mark.asyncio
    async def test_intervention_page_empty(
        self,
        _db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """intervention_page with no pending matches returns HTML with empty state."""
        from pullbox.ui.routes import intervention_page

        async with _db_factory() as session:
            resp = await intervention_page(
                request=_mock_request(),
                user=MagicMock(),
                session=session,
            )

        assert resp.status_code == 200
        body = resp.body.decode()
        assert "Intervention Queue" in body
        assert "No pending matches" in body
        assert 'class="downloads-table-wrap"' in body
        assert re.search(
            r'data-testid="intervention-select-mode-toggle"[^>]*\sdisabled(?:\s|>|=)', body
        )

    @pytest.mark.asyncio
    async def test_intervention_page_with_matches(
        self,
        _db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """intervention_page with seeded data renders match cards."""
        from pullbox.ui.routes import intervention_page

        await _seed_pending_matches(_db_factory, count=2)

        async with _db_factory() as session:
            resp = await intervention_page(
                request=_mock_request(),
                user=MagicMock(),
                session=session,
            )

        assert resp.status_code == 200
        body = resp.body.decode()
        assert "Batman 001 (2016)" in body
        assert "NZBgeek" in body
        assert re.search(
            r'<a\s+href="/issues/\d+"\s+hx-boost="false"\s+class="downloads-issue-link">',
            body,
        )
        assert ":data-intervention-bulk-busy=\"bulkActionBusy ? 'true' : 'false'\"" in body
        assert "hx-on::before-request=\"bulkActionBusy = 'approve'\"" in body
        assert "hx-on::before-request=\"bulkActionBusy = 'reject'\"" in body
        assert "Approving..." in body
        assert "Rejecting..." in body
        assert ':disabled="bulkActionBusy || selectedIds.length === 0"' in body
        assert not re.search(
            r'data-testid="intervention-select-mode-toggle"[^>]*\sdisabled(?:\s|>|=)', body
        )

    @pytest.mark.asyncio
    async def test_intervention_page_paginates_at_25_rows(
        self,
        _db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """intervention_page paginates pending matches in 25-row pages."""
        from pullbox.ui.routes import intervention_page

        await _seed_pending_matches(_db_factory, count=30)

        async with _db_factory() as session:
            first_page = await intervention_page(
                request=_mock_request(),
                user=MagicMock(),
                session=session,
            )
            second_page = await intervention_page(
                request=_mock_request(),
                user=MagicMock(),
                session=session,
                page=2,
            )

        first_body = first_page.body.decode()
        second_body = second_page.body.decode()

        assert len(re.findall(r'data-testid="intervention-item-\d+"', first_body)) == 25
        assert 'hx-swap="outerHTML"' in first_body
        assert "show:window:top" not in first_body
        assert 'data-testid="intervention-footer-dock"' in first_body
        assert 'id="pagination-next"' in first_body
        assert len(re.findall(r'data-testid="intervention-item-\d+"', second_body)) == 5
        assert 'id="pagination-prev"' in second_body

    @pytest.mark.asyncio
    async def test_intervention_selection_ids_returns_all_matching_rows(
        self,
        client: AsyncClient,
        _db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Selection endpoint returns all queue ids matching the current filters."""
        await _seed_pending_matches(_db_factory, count=30)

        resp = await client.get("/intervention/selection-ids")

        assert resp.status_code == 200
        payload = resp.json()
        assert payload["total"] == 30
        assert len(payload["ids"]) == 30

    def test_intervention_selection_state_is_not_pruned_to_visible_page(self) -> None:
        """Pagination should not discard off-page intervention selections."""
        script = Path("src/pullbox/ui/static/js/pullbox.js").read_text(encoding="utf-8")

        prune_body = re.search(
            r"pruneSelection: function \(\) \{(?P<body>.*?)\n    removeSelection:",
            script,
            flags=re.DOTALL,
        )
        assert prune_body is not None
        assert "visibleIds.indexOf(id)" not in prune_body.group("body")
        assert "selectedIds = this.selectedIds.filter" not in prune_body.group("body")
        assert "visibleIds.every" in script

    @pytest.mark.asyncio
    async def test_intervention_page_history_tab_renders_standard_table(
        self,
        _db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """history tab renders the standard history table contract."""
        from pullbox.ui.routes import intervention_page

        await _seed_intervention_history(_db_factory)

        async with _db_factory() as session:
            resp = await intervention_page(
                request=_mock_request(),
                user=MagicMock(),
                session=session,
                tab="history",
            )

        assert resp.status_code == 200
        body = resp.body.decode()
        assert 'data-testid="intervention-tabs"' in body
        assert 'data-testid="intervention-history-panel"' in body
        assert 'data-testid="intervention-history-table"' in body
        assert 'hx-get="/htmx/intervention/history/' in body
        assert 'data-testid="intervention-history-detail-content"' not in body
        assert "Wrong cover scan" not in body
        assert 'class="table-detail-row"' not in body
        assert re.search(
            r'<a\s+href="/issues/\d+"\s+hx-boost="false"\s+class="downloads-issue-link">',
            body,
        )
        assert "Approved" in body
        assert "Rejected" in body
        assert "Expired" in body
        assert 'data-testid="intervention-history-clear"' in body
        assert 'data-testid="intervention-history-toolbar"' in body
        assert 'class="series-toolbar-frame downloads-history-toolbar"' in body
        assert "m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201" in body

    @pytest.mark.asyncio
    async def test_intervention_history_detail_loads_only_on_expand(
        self,
        _db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """History detail route renders the deferred review cards."""
        from pullbox.ui.routes import htmx_intervention_history_detail

        history_ids = await _seed_intervention_history(_db_factory)

        async with _db_factory() as session:
            resp = await htmx_intervention_history_detail(
                request=_mock_request(),
                pending_id=history_ids[1],
                user=MagicMock(),
                session=session,
            )

        assert resp.status_code == 200
        body = resp.body.decode()
        assert f'id="intervention-history-detail-row-{history_ids[1]}"' in body
        assert 'data-testid="intervention-history-detail-content"' in body
        assert "Wrong cover scan" in body
        assert "Review" in body

    @pytest.mark.asyncio
    async def test_htmx_content_history_tab_returns_oob_bundle(
        self,
        _db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """HTMX content refresh returns content plus the footer-dock OOB update."""
        from pullbox.ui.routes import htmx_intervention_content

        await _seed_intervention_history(_db_factory)

        async with _db_factory() as session:
            resp = await htmx_intervention_content(
                request=_mock_request(),
                user=MagicMock(),
                session=session,
                tab="history",
            )

        assert resp.status_code == 200
        body = resp.body.decode()
        assert 'data-testid="intervention-page"' in body
        assert 'data-testid="intervention-tabs"' in body
        assert 'id="page-footer-dock"' in body
        assert 'hx-swap-oob="innerHTML"' in body

    @pytest.mark.asyncio
    async def test_htmx_list_empty(
        self,
        _db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """htmx_intervention_list with no data returns empty-state partial."""
        from pullbox.ui.routes import htmx_intervention_list

        async with _db_factory() as session:
            resp = await htmx_intervention_list(
                request=_mock_request(),
                user=MagicMock(),
                session=session,
            )

        assert resp.status_code == 200
        body = resp.body.decode()
        assert "No pending matches" in body
        assert 'class="downloads-table-wrap"' in body

    @pytest.mark.asyncio
    async def test_htmx_list_with_matches(
        self,
        _db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """htmx_intervention_list renders cards for seeded matches."""
        from pullbox.ui.routes import htmx_intervention_list

        await _seed_pending_matches(_db_factory, count=2)

        async with _db_factory() as session:
            resp = await htmx_intervention_list(
                request=_mock_request(),
                user=MagicMock(),
                session=session,
            )

        assert resp.status_code == 200
        body = resp.body.decode()
        assert "Batman 001 (2016)" in body
        assert "Medium" in body

    @pytest.mark.asyncio
    async def test_htmx_count_zero(
        self,
        _db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """htmx_intervention_count returns hidden badge when no pending matches."""
        from pullbox.ui.routes import htmx_intervention_count

        async with _db_factory() as session:
            resp = await htmx_intervention_count(
                request=_mock_request(),
                user=MagicMock(),
                session=session,
            )

        assert resp.status_code == 200
        body = resp.body.decode()
        assert 'data-sidebar-count="0"' in body
        assert "opacity-0" in body
        assert 'aria-hidden="true"' in body

    @pytest.mark.asyncio
    async def test_htmx_count_nonzero(
        self,
        _db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """htmx_intervention_count returns badge HTML with count."""
        from pullbox.ui.routes import htmx_intervention_count

        await _seed_pending_matches(_db_factory, count=3)

        async with _db_factory() as session:
            resp = await htmx_intervention_count(
                request=_mock_request(),
                user=MagicMock(),
                session=session,
            )

        assert resp.status_code == 200
        body = resp.body.decode()
        assert "3" in body
        assert "count-badge-warning" in body

    @pytest.mark.asyncio
    async def test_htmx_approve_success(
        self,
        _db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """htmx_intervention_approve returns success HTML on approval."""
        from pullbox.ui.routes import htmx_intervention_approve

        pm_ids = await _seed_pending_matches(_db_factory, count=1)

        mock_download = MagicMock()
        mock_download.id = 42
        mock_download.issue_id = 1
        mock_download.title = "Batman 001 (2016) [Digital] Release0.cbz"
        mock_download.state = "sent"

        async with _db_factory() as session:
            with (
                patch(
                    "pullbox.composition.providers.build_registry",
                    new_callable=AsyncMock,
                    return_value=(MagicMock(), {}),
                ),
                patch(
                    "pullbox.services.intervention_service.InterventionService.approve_match",
                    new_callable=AsyncMock,
                    return_value=mock_download,
                ),
            ):
                resp = await htmx_intervention_approve(
                    request=_mock_request(),
                    pending_id=pm_ids[0],
                    user=MagicMock(),
                    session=session,
                )

        assert resp.status_code == 200
        body = resp.body.decode()
        assert "Approved" in body
        assert 'data-testid="intervention-item-result-' in body

    @pytest.mark.asyncio
    async def test_htmx_approve_not_found(
        self,
        _db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """htmx_intervention_approve returns 404 for missing pending match."""
        from pullbox.ui.routes import htmx_intervention_approve

        async with _db_factory() as session:
            resp = await htmx_intervention_approve(
                request=_mock_request(),
                pending_id=99999,
                user=MagicMock(),
                session=session,
            )

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_htmx_approve_no_clients(
        self,
        _db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """htmx_intervention_approve returns error when no download clients."""
        from pullbox.ui.routes import htmx_intervention_approve

        pm_ids = await _seed_pending_matches(_db_factory, count=1)

        async with _db_factory() as session:
            with patch(
                "pullbox.composition.providers.build_registry",
                new_callable=AsyncMock,
                return_value=None,
            ):
                resp = await htmx_intervention_approve(
                    request=_mock_request(),
                    pending_id=pm_ids[0],
                    user=MagicMock(),
                    session=session,
                )

        assert resp.status_code == 200
        body = resp.body.decode()
        assert "No download clients are configured" in body
        assert "Could Not Approve" in body

    @pytest.mark.asyncio
    async def test_htmx_approve_service_error(
        self,
        _db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """htmx_intervention_approve returns error HTML when service raises."""
        from pullbox.ui.routes import htmx_intervention_approve

        pm_ids = await _seed_pending_matches(_db_factory, count=1)

        async with _db_factory() as session:
            with (
                patch(
                    "pullbox.composition.providers.build_registry",
                    new_callable=AsyncMock,
                    return_value=(MagicMock(), {}),
                ),
                patch(
                    "pullbox.services.intervention_service.InterventionService.approve_match",
                    new_callable=AsyncMock,
                    side_effect=ValueError("Match not pending"),
                ),
            ):
                resp = await htmx_intervention_approve(
                    request=_mock_request(),
                    pending_id=pm_ids[0],
                    user=MagicMock(),
                    session=session,
                )

        assert resp.status_code == 200
        body = resp.body.decode()
        assert "Could Not Approve" in body
        assert "Failed to send this release" in body

    @pytest.mark.asyncio
    async def test_htmx_reject_success(
        self,
        _db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """htmx_intervention_reject returns dismissed HTML on rejection."""
        from pullbox.ui.routes import htmx_intervention_reject

        pm_ids = await _seed_pending_matches(_db_factory, count=1)

        async with _db_factory() as session:
            resp = await htmx_intervention_reject(
                request=_mock_request(),
                pending_id=pm_ids[0],
                user=MagicMock(),
                session=session,
            )

        assert resp.status_code == 200
        body = resp.body.decode()
        assert "Rejected" in body
        assert 'data-testid="intervention-item-result-' in body
        assert "added to the blocklist" in body

    @pytest.mark.asyncio
    async def test_htmx_reject_queue_refresh_sets_blocklist_toast(
        self,
        _db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Queue refresh reject path emits the blocklist success toast."""
        from pullbox.ui.routes import htmx_intervention_reject

        pm_ids = await _seed_pending_matches(_db_factory, count=1)
        req = _mock_request()
        req.headers = {"HX-Target": "intervention-queue-results"}

        async with _db_factory() as session:
            resp = await htmx_intervention_reject(
                request=req,
                pending_id=pm_ids[0],
                user=MagicMock(),
                session=session,
            )

        assert resp.status_code == 200
        assert "No pending matches" in resp.body.decode()
        trigger = json.loads(resp.headers["HX-Trigger"])
        assert trigger == {
            "toast": {
                "message": "Release rejected and added to the blocklist.",
                "level": "success",
            }
        }

    @pytest.mark.asyncio
    async def test_htmx_reject_not_found(
        self,
        _db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """htmx_intervention_reject returns 404 for missing pending match."""
        from pullbox.ui.routes import htmx_intervention_reject

        async with _db_factory() as session:
            resp = await htmx_intervention_reject(
                request=_mock_request(),
                pending_id=99999,
                user=MagicMock(),
                session=session,
            )

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_htmx_reject_already_resolved(
        self,
        _db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """htmx_intervention_reject returns 404 when reject_match raises ValueError."""
        from pullbox.ui.routes import htmx_intervention_reject

        pm_ids = await _seed_pending_matches(_db_factory, count=1)

        async with _db_factory() as session:
            with patch(
                "pullbox.services.intervention_service.InterventionService.reject_match",
                new_callable=AsyncMock,
                side_effect=ValueError("Not pending"),
            ):
                resp = await htmx_intervention_reject(
                    request=_mock_request(),
                    pending_id=pm_ids[0],
                    user=MagicMock(),
                    session=session,
                )

        assert resp.status_code == 404


class TestBulkActionsUI:
    """Tests for bulk approve/reject HTMX endpoints."""

    @pytest.mark.asyncio
    async def test_bulk_approve_htmx(
        self,
        client: AsyncClient,
        _db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """POST /htmx/intervention/bulk-approve returns refreshed list."""
        pm_ids = await _seed_pending_matches(_db_factory, count=2)

        mock_download = MagicMock()
        mock_download.id = 42
        mock_download.issue_id = 1
        mock_download.title = "Batman 001 (2016) [Digital] Release0.cbz"
        mock_download.state = "sent"

        with (
            patch(
                "pullbox.composition.providers.build_registry",
                new_callable=AsyncMock,
                return_value=(MagicMock(), {}),
            ),
            patch(
                "pullbox.services.intervention_service.InterventionService.approve_match",
                new_callable=AsyncMock,
                return_value=mock_download,
            ),
        ):
            resp = await client.post(
                "/htmx/intervention/bulk-approve",
                data={"ids": ",".join(str(i) for i in pm_ids)},
            )

        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        html = resp.text
        assert 'data-testid="intervention-page"' in html
        assert 'data-testid="intervention-list"' in html

    @pytest.mark.asyncio
    async def test_bulk_reject_htmx(
        self,
        client: AsyncClient,
        _db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """POST /htmx/intervention/bulk-reject returns refreshed list."""
        pm_ids = await _seed_pending_matches(_db_factory, count=2)

        resp = await client.post(
            "/htmx/intervention/bulk-reject",
            data={"ids": ",".join(str(i) for i in pm_ids)},
        )

        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        html = resp.text
        assert 'data-testid="intervention-page"' in html
        assert "No pending matches" in html
        trigger = json.loads(resp.headers["HX-Trigger"])
        assert trigger == {
            "toast": {
                "message": "Rejected 2 releases and added them to the blocklist.",
                "level": "success",
            }
        }


class TestNavBadge:
    """Tests for the Intervention nav badge in the sidebar."""

    @pytest.mark.asyncio
    async def test_nav_badge_container_in_page(
        self,
        client: AsyncClient,
    ) -> None:
        """Authenticated page sidebar includes HTMX-polled intervention badge."""
        resp = await client.get("/intervention")

        assert resp.status_code == 200
        html = resp.text
        assert 'hx-get="/htmx/intervention/count"' in html

    @pytest.mark.asyncio
    async def test_nav_badge_shows_count_when_pending(
        self,
        client: AsyncClient,
        _db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Badge endpoint returns amber badge HTML when pending matches exist."""
        await _seed_pending_matches(_db_factory, count=3)

        resp = await client.get("/htmx/intervention/count")

        assert resp.status_code == 200
        html = resp.text
        assert "3" in html
        assert "count-badge-warning" in html

    @pytest.mark.asyncio
    async def test_nav_badge_empty_when_no_pending(
        self,
        client: AsyncClient,
    ) -> None:
        """Badge endpoint returns a layout-stable invisible fragment when no pending matches."""
        resp = await client.get("/htmx/intervention/count")

        assert resp.status_code == 200
        assert "opacity-0" in resp.text
        assert 'data-sidebar-count="0"' in resp.text
        assert "no-store" in resp.headers["cache-control"]


class TestDashboardPendingCount:
    """Direct handler tests for pending_match_count on the dashboard."""

    @pytest.mark.asyncio
    async def test_dashboard_shows_pending_count(
        self,
        _db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Dashboard includes pending match count when matches exist."""
        from pullbox.ui.routes import dashboard

        await _seed_pending_matches(_db_factory, count=3)

        req = _mock_request()
        req.url.path = "/"

        async with _db_factory() as session:
            resp = await dashboard(
                request=req,
                user=MagicMock(),
                session=session,
            )

        assert resp.status_code == 200
        body = resp.body.decode()
        assert "3" in body
        assert "/intervention" in body

    @pytest.mark.asyncio
    async def test_dashboard_hides_banner_when_zero(
        self,
        _db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Dashboard hides intervention banner when no pending matches."""
        from pullbox.ui.routes import dashboard

        req = _mock_request()
        req.url.path = "/"

        async with _db_factory() as session:
            resp = await dashboard(
                request=req,
                user=MagicMock(),
                session=session,
            )

        assert resp.status_code == 200
        body = resp.body.decode()
        assert "pending match" not in body
