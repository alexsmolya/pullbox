"""Tests for type-specific search query building — ESM Phase 3, Task 3.2.

Covers:
- Standard ISSUE type returns plain query (no type keywords)
- TPB appends "TPB" and "Vol" keyword variations
- ANNUAL appends "Annual" keyword
- HC appends "HC" and "Hardcover" keyword variations
- Multiple variations returned as a list
- ONE_SHOT and SPECIAL (no keywords) return plain query
- GN, OMNIBUS, DELUXE, COMPENDIUM append correct keywords
- Issue number formatting (integer vs float)

Run:
    pytest tests/unit/test_type_queries.py -v
"""

from __future__ import annotations

import pytest

from pullbox.models.issue import IssueType
from pullbox.services.search_service import _build_type_queries


class TestTypeQueryBuilding:
    """Tests for _build_type_queries() query string generation."""

    def test_standard_issue_no_keywords_uses_issue_variants(self) -> None:
        """ISSUE type returns issue-number variants without extra type keywords."""
        result = _build_type_queries("Batman", 5.0, IssueType.ISSUE)
        assert result == ["Batman 5", "Batman 05", "Batman #05", "Batman 005", "Batman #005"]

    def test_standard_issue_one_includes_padded_and_hash_variants(self) -> None:
        """ISSUE #1 includes variants needed by strict torrent indexer matching."""
        result = _build_type_queries("Absolute Flash", 1.0, IssueType.ISSUE)
        assert result == [
            "Absolute Flash 1",
            "Absolute Flash 01",
            "Absolute Flash #01",
            "Absolute Flash 001",
            "Absolute Flash #001",
        ]

    def test_standard_issue_no_issue_number(self) -> None:
        """ISSUE type with no issue number returns just series title."""
        result = _build_type_queries("Batman", None, IssueType.ISSUE)
        assert result == ["Batman"]

    def test_tpb_appends_keywords(self) -> None:
        """TPB type returns variations with 'TPB' and 'Vol'."""
        result = _build_type_queries("Batman", 3.0, IssueType.TPB)
        assert "Batman TPB 3" in result
        assert "Batman Vol 3" in result

    def test_annual_appends_annual(self) -> None:
        """ANNUAL type returns query with 'Annual' keyword."""
        result = _build_type_queries("Batman", 2.0, IssueType.ANNUAL)
        assert "Batman Annual 2" in result

    def test_hc_appends_keywords(self) -> None:
        """HC type returns variations with 'HC' and 'Hardcover'."""
        result = _build_type_queries("Batman", 1.0, IssueType.HC)
        assert "Batman HC 1" in result
        assert "Batman Hardcover 1" in result

    def test_multiple_variations_returned(self) -> None:
        """Non-standard types return a list with multiple query strings."""
        result = _build_type_queries("Batman", 5.0, IssueType.TPB)
        assert len(result) >= 2
        assert all(isinstance(q, str) for q in result)

    def test_omnibus_appends_keyword(self) -> None:
        """OMNIBUS type appends 'Omnibus' keyword."""
        result = _build_type_queries("Batman", 1.0, IssueType.OMNIBUS)
        assert "Batman Omnibus 1" in result

    def test_gn_appends_keywords(self) -> None:
        """GN type returns variations with 'GN' and 'Graphic Novel'."""
        result = _build_type_queries("Batman", 1.0, IssueType.GN)
        assert "Batman GN 1" in result
        assert "Batman Graphic Novel 1" in result

    def test_ogn_appends_keywords(self) -> None:
        """OGN type returns variations with 'OGN' and 'Original Graphic Novel'."""
        result = _build_type_queries("Batman", 1.0, IssueType.OGN)
        assert "Batman OGN 1" in result
        assert "Batman Original Graphic Novel 1" in result

    def test_deluxe_appends_keywords(self) -> None:
        """DELUXE type returns variations with 'Deluxe Edition' and 'Deluxe'."""
        result = _build_type_queries("Batman", 1.0, IssueType.DELUXE)
        assert "Batman Deluxe Edition 1" in result
        assert "Batman Deluxe 1" in result

    def test_compendium_appends_keyword(self) -> None:
        """COMPENDIUM type appends 'Compendium' keyword."""
        result = _build_type_queries("Batman", 1.0, IssueType.COMPENDIUM)
        assert "Batman Compendium 1" in result

    def test_one_shot_no_keywords(self) -> None:
        """ONE_SHOT has no special keywords, but still gets issue-number variants."""
        result = _build_type_queries("Batman", 1.0, IssueType.ONE_SHOT)
        assert result == ["Batman 1", "Batman 01", "Batman #01", "Batman 001", "Batman #001"]

    def test_special_no_keywords(self) -> None:
        """SPECIAL has no special keywords, but still gets issue-number variants."""
        result = _build_type_queries("Batman", 1.0, IssueType.SPECIAL)
        assert result == ["Batman 1", "Batman 01", "Batman #01", "Batman 001", "Batman #001"]

    def test_integer_issue_number_no_decimal(self) -> None:
        """Integer-valued floats format without decimal (5.0 → '5')."""
        result = _build_type_queries("Batman", 5.0, IssueType.ISSUE)
        assert "Batman 5" in result
        assert "Batman 05" in result

    def test_fractional_issue_number_preserved(self) -> None:
        """Non-integer floats preserve decimal (1.5 → '1.5')."""
        result = _build_type_queries("Batman", 1.5, IssueType.ISSUE)
        assert result == ["Batman 1.5"]

    def test_fractional_issue_with_type_keywords(self) -> None:
        """Non-integer issue numbers work with type keywords too."""
        result = _build_type_queries("Batman", 2.5, IssueType.TPB)
        assert "Batman TPB 2.5" in result
        assert "Batman Vol 2.5" in result

    def test_none_issue_number_with_type_keywords(self) -> None:
        """Type keywords work without an issue number."""
        result = _build_type_queries("Batman", None, IssueType.TPB)
        assert "Batman TPB" in result
        assert "Batman Vol" in result


class TestSearchForIssueTypeQueries:
    """Tests that search_for_issue uses type-specific queries for non-standard types."""

    @pytest.mark.asyncio
    async def test_nonstandard_type_searches_multiple_queries(self) -> None:
        """Non-standard issue type triggers multiple search queries."""
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, MagicMock

        from pullbox.models.issue import IssueType
        from pullbox.services.search_service import SearchService

        mock_registry = MagicMock()
        svc = SearchService(mock_registry)

        # Track all queries passed to _search_indexers
        queries_seen: list[object] = []

        async def tracking_search(query: object, indexer_configs: object = None) -> list[object]:
            queries_seen.append(query)
            return []

        svc._search_indexers = tracking_search  # type: ignore[assignment]

        # Mock session with a TPB issue
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.first.return_value = SimpleNamespace(
            issue_id=1,
            series_id=1,
            series_title="Batman",
            issue_number=3.0,
            issue_type=IssueType.TPB,
            issue_title=None,
            series_year=2020,
            alternate_names=None,
        )
        mock_session.execute.return_value = mock_result

        await svc.search_for_issue(mock_session, 1)

        # TPB should produce 4 query variations (TPB, Vol, plain, plain+year)
        assert len(queries_seen) == 4
        titles = [q.series_title for q in queries_seen]
        assert "Batman TPB 3" in titles
        assert "Batman Vol 3" in titles
        assert "Batman" in titles
        assert "Batman 2020" in titles

    @pytest.mark.asyncio
    async def test_standard_type_single_query(self) -> None:
        """Standard ISSUE type still uses a single query."""
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, MagicMock

        from pullbox.models.issue import IssueType
        from pullbox.services.search_service import SearchService

        mock_registry = MagicMock()
        svc = SearchService(mock_registry)

        queries_seen: list[object] = []

        async def tracking_search(query: object, indexer_configs: object = None) -> list[object]:
            queries_seen.append(query)
            return []

        svc._search_indexers = tracking_search  # type: ignore[assignment]

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.first.return_value = SimpleNamespace(
            issue_id=1,
            series_id=1,
            series_title="Batman",
            issue_number=5.0,
            issue_type=IssueType.ISSUE,
            issue_title=None,
            series_year=2020,
            alternate_names=None,
        )
        mock_session.execute.return_value = mock_result

        await svc.search_for_issue(mock_session, 1)

        # Standard issue: issue-number variants + year-augmented "Batman 2020"
        assert len(queries_seen) == 6
        titles = [q.series_title for q in queries_seen]
        assert "Batman 5" in titles
        assert "Batman 05" in titles
        assert "Batman #05" in titles
        assert "Batman 005" in titles
        assert "Batman #005" in titles
        assert "Batman 2020" in titles

    @pytest.mark.asyncio
    async def test_deduplicates_results_across_queries(self) -> None:
        """Results from multiple query variations are deduplicated by download_url."""
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, MagicMock

        from pullbox.models.issue import IssueType
        from pullbox.providers.base import ReleaseResult
        from pullbox.services.search_service import SearchService

        mock_registry = MagicMock()
        svc = SearchService(mock_registry)

        dupe_release = ReleaseResult(
            title="Batman Vol 03 TPB",
            indexer_name="NZBgeek",
            download_url="https://indexer.example.com/dl/same",
            size_bytes=100_000_000,
            age_days=2,
            seeders=None,
            leechers=None,
            grabs=None,
            is_torrent=False,
            category=None,
            published_at=None,
        )

        call_count = 0

        async def multi_search(
            query: object, indexer_configs: object = None
        ) -> list[ReleaseResult]:
            nonlocal call_count
            call_count += 1
            # Both queries return the same release
            return [dupe_release]

        svc._search_indexers = multi_search  # type: ignore[assignment]

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.first.return_value = SimpleNamespace(
            issue_id=1,
            series_id=1,
            series_title="Batman",
            issue_number=3.0,
            issue_type=IssueType.TPB,
            issue_title=None,
            series_year=2020,
            alternate_names=None,
        )
        mock_session.execute.return_value = mock_result

        results = await svc.search_for_issue(mock_session, 1)

        # Four queries were made (TPB, Vol, plain, plain+year), but duplicate filtered out
        assert call_count == 4
        assert len(results) == 1
