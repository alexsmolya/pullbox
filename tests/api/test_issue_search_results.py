"""Tests for the interactive search results endpoint and validate_all_results().

Verifies:
- ReleaseValidator.validate_all_results() returns both matched and rejected lists
- Matched results are sorted by confidence descending
- GET /api/v1/issues/{id}/search-results returns both arrays with full context
- Rejected results include rejection reasons
- Matched results include match details
- Auto-grabbable flag works correctly
- Empty results handled gracefully
- Nonexistent issue returns 404

Run:
    pytest tests/api/test_issue_search_results.py -v
"""

from __future__ import annotations

import hashlib
import os
import sys
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from pullbox.models import Base
from pullbox.models.issue import Issue, IssueStatus, IssueType
from pullbox.models.library import MatchConfidence
from pullbox.models.series import Series, SeriesStatus, SeriesType
from pullbox.models.user import APIKey, User
from pullbox.providers.base import ReleaseResult
from pullbox.services.auth_service import AuthService
from pullbox.services.release_validator import ReleaseValidator

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-search-results")


# ── Test Data ──────────────────────────────────────────────────────────


def _make_release(
    title: str,
    indexer_name: str = "NZBgeek",
    *,
    size_bytes: int | None = 100_000_000,
    age_days: int | None = 5,
    is_torrent: bool = False,
) -> ReleaseResult:
    return ReleaseResult(
        title=title,
        indexer_name=indexer_name,
        download_url=f"https://indexer.example.com/dl/{title.replace(' ', '_')}",
        size_bytes=size_bytes,
        age_days=age_days,
        seeders=10 if is_torrent else None,
        leechers=2 if is_torrent else None,
        grabs=50 if not is_torrent else None,
        is_torrent=is_torrent,
        category="comics",
        published_at=None,
    )


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
    raw_key = "pb_k1_" + "d" * 64
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    async with _db_factory() as session:
        user = User(
            username="searchuser",
            password_hash=AuthService.hash_password("Test@1234"),
        )
        session.add(user)
        await session.flush()
        session.add(APIKey(user_id=user.id, key_hash=key_hash, name="search-test"))
        await session.commit()
    return raw_key


@pytest.fixture
async def client(
    _db_factory: async_sessionmaker[AsyncSession],
    _api_key_header: str,
) -> AsyncGenerator[AsyncClient, None]:
    """HTTP client authenticated via API key (bypasses CSRF)."""
    from pullbox.api.deps import get_db_dep
    from pullbox.api.middleware import reset_setup_cache
    from pullbox.app import create_app

    app = create_app()

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


async def _create_issue(
    factory: async_sessionmaker[AsyncSession],
    *,
    series_title: str = "Batman",
    year_start: int = 2016,
    issue_number: float = 1.0,
) -> int:
    """Seed a series + issue, return the issue_id."""
    async with factory() as session:
        series = Series(
            comicvine_id=99900,
            title=series_title,
            sort_title=series_title,
            year_start=year_start,
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
            issue_number=issue_number,
            title=f"Issue #{int(issue_number)}",
            status=IssueStatus.WANTED,
        )
        session.add(issue)
        await session.commit()
        return issue.id


# ── Unit Tests: validate_all_results() ─────────────────────────────────


@pytest.mark.asyncio
async def test_validate_all_returns_matched_and_rejected() -> None:
    """Feed mixed results — verify both matched and rejected lists populated."""
    validator = ReleaseValidator()

    results = [
        _make_release("Batman 001 (2016).cbz"),  # match
        _make_release("Superman 005 (2020).cbr"),  # reject: series mismatch
        _make_release("Batman 001 (2016) covers only.cbz"),  # reject: ignore word
        _make_release("Batman 002 (2016).cbz"),  # reject: issue mismatch
    ]

    matched, rejected = validator.validate_all_results(
        results,
        wanted_series="Batman",
        wanted_issue=1.0,
        wanted_year=2016,
    )

    assert len(matched) == 1
    assert len(rejected) == 3
    assert matched[0].is_match is True
    assert all(not r.is_match for r in rejected)


@pytest.mark.asyncio
async def test_validate_all_matched_sorted_by_confidence() -> None:
    """Matched list should be sorted HIGH > MEDIUM > LOW."""
    validator = ReleaseValidator()

    results = [
        # Fuzzy match with no year → LOW confidence
        _make_release("Batmans 001.cbz"),
        # Exact match with year → HIGH confidence
        _make_release("Batman 001 (2016).cbz"),
        # Exact match without year → MEDIUM confidence
        _make_release("Batman 001.cbz"),
    ]

    matched, _rejected = validator.validate_all_results(
        results,
        wanted_series="Batman",
        wanted_issue=1.0,
        wanted_year=2016,
    )

    assert len(matched) >= 2
    confidences = [v.confidence for v in matched]
    confidence_order = [MatchConfidence.HIGH, MatchConfidence.MEDIUM, MatchConfidence.LOW]
    # Verify ordering: each confidence should come before or equal to the next
    for i in range(len(confidences) - 1):
        assert confidence_order.index(confidences[i]) <= confidence_order.index(confidences[i + 1])


# ── Unit Tests: build_interactive_results() ────────────────────────────


@pytest.mark.asyncio
async def test_build_interactive_results_matched_and_rejected() -> None:
    """build_interactive_results() creates correct schema objects from ValidationResults."""
    from pullbox.api.v1.issues import build_interactive_results
    from pullbox.schemas.search import InteractiveSearchIssue, InteractiveSearchResponse

    validator = ReleaseValidator()
    results = [
        _make_release("Batman 001 (2016).cbz"),
        _make_release("Superman 005 (2020).cbr"),
    ]

    matched_vr, rejected_vr = validator.validate_all_results(
        results,
        wanted_series="Batman",
        wanted_issue=1.0,
        wanted_year=2016,
    )

    matched_items, rejected_items = build_interactive_results(matched_vr, rejected_vr, {})

    # Wrap in response to verify full serialization
    response = InteractiveSearchResponse(
        issue=InteractiveSearchIssue(
            id=1,
            series_title="Batman",
            issue_number=1.0,
            issue_type="issue",
            year=2016,
        ),
        matched=matched_items,
        rejected=rejected_items,
        search_time_ms=42,
    )

    assert len(response.matched) == 1
    assert len(response.rejected) == 1
    assert response.matched[0].confidence == "high"
    assert response.matched[0].auto_grabbable is True
    assert response.matched[0].quality_score > 0
    assert response.matched[0].match_details.parsed_series == "Batman"
    assert response.matched[0].match_details.parsed_issue == 1.0
    assert response.matched[0].match_details.series_similarity > 0.9
    assert response.rejected[0].rejection_reason is not None
    assert response.rejected[0].confidence is None
    assert response.rejected[0].download_url == results[1].download_url
    assert response.rejected[0].indexer_name == results[1].indexer_name
    assert response.rejected[0].is_torrent == results[1].is_torrent
    assert response.search_time_ms == 42

    # Verify JSON serialization round-trips
    data = response.model_dump()
    assert data["issue"]["series_title"] == "Batman"
    assert isinstance(data["matched"][0]["quality_score"], float)
    assert data["rejected"][0]["download_url"] == results[1].download_url


@pytest.mark.asyncio
async def test_build_interactive_results_auto_grabbable_logic() -> None:
    """Interactive auto-grabbable mirrors per-type automated routing thresholds."""
    from pullbox.api.v1.issues import build_interactive_results

    validator = ReleaseValidator()
    results = [
        _make_release("Batman 001 (2016).cbz"),  # HIGH
        _make_release("Batman 001.cbz"),  # MEDIUM
    ]

    matched_vr, rejected_vr = validator.validate_all_results(
        results,
        wanted_series="Batman",
        wanted_issue=1.0,
        wanted_year=2016,
    )

    matched_items, _ = build_interactive_results(
        matched_vr,
        rejected_vr,
        {},
        issue_type=IssueType.ISSUE,
        type_thresholds={"issue": "medium"},
    )

    high_items = [m for m in matched_items if m.confidence == "high"]
    medium_items = [m for m in matched_items if m.confidence == "medium"]

    assert len(high_items) >= 1
    for item in high_items:
        assert item.auto_grabbable is True
        assert item.quality_score > 10

    assert len(medium_items) >= 1
    for item in medium_items:
        assert item.auto_grabbable is True

    tpb_items, _ = build_interactive_results(
        matched_vr,
        rejected_vr,
        {},
        issue_type=IssueType.TPB,
        type_thresholds={"tpb": "high"},
    )
    for item in [m for m in tpb_items if m.confidence == "medium"]:
        assert item.auto_grabbable is False


@pytest.mark.asyncio
async def test_build_interactive_results_empty_inputs() -> None:
    """Empty validation results produce empty item lists."""
    from pullbox.api.v1.issues import build_interactive_results

    matched_items, rejected_items = build_interactive_results([], [], {})
    assert matched_items == []
    assert rejected_items == []


@pytest.mark.asyncio
async def test_build_interactive_results_custom_eval_kwargs() -> None:
    """Custom eval_kwargs (min_score, confidence_blend) affect scoring."""
    from pullbox.api.v1.issues import build_interactive_results

    validator = ReleaseValidator()
    results = [_make_release("Batman 001 (2016).cbz")]

    matched_vr, rejected_vr = validator.validate_all_results(
        results,
        wanted_series="Batman",
        wanted_issue=1.0,
        wanted_year=2016,
    )

    # With default kwargs
    items_default, _ = build_interactive_results(matched_vr, rejected_vr, {})

    # With high min_score — should still be auto_grabbable since it's HIGH
    items_custom, _ = build_interactive_results(matched_vr, rejected_vr, {"confidence_blend": 0.80})

    # Different blend should produce different quality scores
    assert items_default[0].quality_score != items_custom[0].quality_score


# ── API Tests ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_returns_matched_and_rejected(
    client: AsyncClient,
    _db_factory: async_sessionmaker[AsyncSession],
) -> None:
    """HTTP endpoint returns both matched and rejected arrays."""
    issue_id = await _create_issue(_db_factory)

    mock_results = [
        _make_release("Batman 001 (2016).cbz"),
        _make_release("Superman 005 (2020).cbr"),
    ]

    mock_registry = AsyncMock()
    with (
        patch(
            "pullbox.composition.providers.build_registry",
            new_callable=AsyncMock,
            return_value=(mock_registry, {}),
        ),
        patch(
            "pullbox.services.search_service.SearchService.search_for_issue",
            new_callable=AsyncMock,
            return_value=mock_results,
        ),
    ):
        resp = await client.get(f"/api/v1/issues/{issue_id}/search-results")

    assert resp.status_code == 200
    data = resp.json()
    assert "matched" in data
    assert "rejected" in data
    assert len(data["matched"]) == 1
    assert len(data["rejected"]) == 1
    assert data["issue"]["id"] == issue_id
    assert "search_time_ms" in data
    assert "details" not in data
    assert "search_details" not in data
    assert "top_rejected" not in data
    assert "rejected_diagnostics_count" not in data
    for item in [*data["matched"], *data["rejected"]]:
        assert "query" not in item
        assert "reason_summary" not in item


@pytest.mark.asyncio
async def test_rejected_includes_reason(
    client: AsyncClient,
    _db_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Each rejected result has a rejection_reason string."""
    issue_id = await _create_issue(_db_factory)

    mock_results = [
        _make_release("Superman 005 (2020).cbr"),
        _make_release("Random Garbage Title"),
    ]

    mock_registry = AsyncMock()
    with (
        patch(
            "pullbox.composition.providers.build_registry",
            new_callable=AsyncMock,
            return_value=(mock_registry, {}),
        ),
        patch(
            "pullbox.services.search_service.SearchService.search_for_issue",
            new_callable=AsyncMock,
            return_value=mock_results,
        ),
    ):
        resp = await client.get(f"/api/v1/issues/{issue_id}/search-results")

    assert resp.status_code == 200
    data = resp.json()
    for rejected in data["rejected"]:
        assert "rejection_reason" in rejected
        assert isinstance(rejected["rejection_reason"], str)
        assert len(rejected["rejection_reason"]) > 0


@pytest.mark.asyncio
async def test_includes_match_details(
    client: AsyncClient,
    _db_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Each matched result has parsed_series, parsed_issue, series_similarity."""
    issue_id = await _create_issue(_db_factory)

    mock_results = [_make_release("Batman 001 (2016).cbz")]

    mock_registry = AsyncMock()
    with (
        patch(
            "pullbox.composition.providers.build_registry",
            new_callable=AsyncMock,
            return_value=(mock_registry, {}),
        ),
        patch(
            "pullbox.services.search_service.SearchService.search_for_issue",
            new_callable=AsyncMock,
            return_value=mock_results,
        ),
    ):
        resp = await client.get(f"/api/v1/issues/{issue_id}/search-results")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["matched"]) == 1
    details = data["matched"][0]["match_details"]
    assert details["parsed_series"] is not None
    assert details["parsed_issue"] is not None
    assert details["series_similarity"] > 0


@pytest.mark.asyncio
async def test_auto_grabbable_flag(
    client: AsyncClient,
    _db_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Auto-grabbable reflects the standard issue type's medium threshold."""
    issue_id = await _create_issue(_db_factory)

    mock_results = [
        _make_release("Batman 001 (2016).cbz"),  # HIGH confidence (exact + year)
        _make_release("Batman 001.cbz"),  # MEDIUM confidence (exact, no year)
    ]

    mock_registry = AsyncMock()
    with (
        patch(
            "pullbox.composition.providers.build_registry",
            new_callable=AsyncMock,
            return_value=(mock_registry, {}),
        ),
        patch(
            "pullbox.services.search_service.SearchService.search_for_issue",
            new_callable=AsyncMock,
            return_value=mock_results,
        ),
    ):
        resp = await client.get(f"/api/v1/issues/{issue_id}/search-results")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["matched"]) == 2

    high_results = [m for m in data["matched"] if m["confidence"] == "high"]
    medium_results = [m for m in data["matched"] if m["confidence"] == "medium"]

    assert len(high_results) >= 1
    for r in high_results:
        assert r["auto_grabbable"] is True

    assert len(medium_results) >= 1
    for r in medium_results:
        assert r["auto_grabbable"] is True


@pytest.mark.asyncio
async def test_no_results_returns_empty(
    client: AsyncClient,
    _db_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Empty indexer response → empty matched and rejected arrays."""
    issue_id = await _create_issue(_db_factory)

    mock_registry = AsyncMock()
    with (
        patch(
            "pullbox.composition.providers.build_registry",
            new_callable=AsyncMock,
            return_value=(mock_registry, {}),
        ),
        patch(
            "pullbox.services.search_service.SearchService.search_for_issue",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        resp = await client.get(f"/api/v1/issues/{issue_id}/search-results")

    assert resp.status_code == 200
    data = resp.json()
    assert data["matched"] == []
    assert data["rejected"] == []
    assert data["search_time_ms"] >= 0


@pytest.mark.asyncio
async def test_nonexistent_issue_returns_404(client: AsyncClient) -> None:
    """Missing issue returns 404."""
    resp = await client.get("/api/v1/issues/99999/search-results")
    assert resp.status_code == 404
