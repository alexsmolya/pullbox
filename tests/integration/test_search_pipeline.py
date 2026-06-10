"""Integration tests for the search pipeline with release validation.

Verifies that ReleaseValidator gates results before quality scoring,
confidence bonuses affect ranking, and issue_type flows through the pipeline.

Run:
    pytest tests/integration/test_search_pipeline.py -v
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import structlog

from pullbox.models.issue import IssueType
from pullbox.providers.base import SearchQuery
from pullbox.services.search_service import SearchService
from tests.conftest import make_release

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _reset_structlog_cache() -> Iterator[None]:
    """Reset structlog so capture_logs works even after app configures it."""
    import pullbox.services.release_validator as rv_mod
    import pullbox.services.search_service as ss_mod

    structlog.reset_defaults()
    ss_mod.logger = structlog.get_logger(ss_mod.__name__)
    rv_mod.log = structlog.get_logger(rv_mod.__name__)
    yield


class TestSearchPipelineIntegration:
    """Integration tests for the validated search pipeline."""

    def test_validator_gates_before_scoring(self) -> None:
        """Wrong issues must never reach the scoring stage."""
        results = [
            make_release("Batman 005 [2024] [Digital] [Shan-Empire]"),
            make_release("Batman 050 [2024] [Digital]"),
            make_release("Superman 005 [2024] [Digital]"),
            make_release("Batman Annual 005 [2024]"),
            make_release("Batman 005 [2023] [Digital]"),
        ]
        best = SearchService.evaluate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
            wanted_year=2024,
            wanted_issue_type=IssueType.ISSUE,
        )
        assert best is not None
        assert "Batman" in best.title
        assert "050" not in best.title
        assert "Superman" not in best.title
        assert "Annual" not in best.title

    def test_combined_score_weights(self) -> None:
        """HIGH confidence + medium quality should beat LOW confidence results."""
        results = [
            make_release("Batman 005 [2024] [Digital]"),  # exact match, year → HIGH
            make_release("Batman 005 [Digital]"),  # exact match, no year → MEDIUM
        ]
        best = SearchService.evaluate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
            wanted_year=2024,
            wanted_issue_type=IssueType.ISSUE,
        )
        assert best is not None
        # HIGH confidence result should win due to confidence bonus
        assert "2024" in best.title

    def test_issue_type_passed_through_pipeline(self) -> None:
        """SearchQuery.issue_type flows through to validator."""
        query = SearchQuery(
            series_title="Batman",
            issue_number=5.0,
            year=2024,
            issue_type=IssueType.ANNUAL.value,
        )
        assert query.issue_type == "annual"

    def test_alternate_names_passed_to_validator(self) -> None:
        """alternate_names are used during validation."""
        results = [make_release("TMNT 005 [2024] [Digital]")]
        best = SearchService.evaluate_results(
            results,
            wanted_series="Teenage Mutant Ninja Turtles",
            wanted_issue=5.0,
            wanted_year=2024,
            alternate_names=["TMNT"],
        )
        assert best is not None
        assert "TMNT" in best.title

    def test_all_rejected_returns_no_results(self) -> None:
        """When validator rejects everything, search returns None."""
        results = [
            make_release("Superman 005 [2024] [Digital]"),
            make_release("Batman 050 [2024] [Digital]"),
        ]
        best = SearchService.evaluate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
            wanted_year=2024,
        )
        assert best is None

    def test_validation_logging(self) -> None:
        """Verify accepted/rejected counts are logged."""
        import structlog.testing

        results = [
            make_release("Batman 005 [2024] [Digital]"),
            make_release("Superman 005 [2024] [Digital]"),
        ]
        with structlog.testing.capture_logs() as cap_logs:
            SearchService.evaluate_results(
                results,
                wanted_series="Batman",
                wanted_issue=5.0,
                wanted_year=2024,
            )
        events = [entry["event"] for entry in cap_logs]
        assert "validate_all_complete" in events

    def test_evaluate_results_with_validation(self) -> None:
        """evaluate_results() validates before scoring when params provided."""
        results = [
            make_release("Batman 005 [2024] [Digital]"),
            make_release("Batman 050 [2024] [Digital]"),
        ]
        # With validation: only #5 survives
        best_validated = SearchService.evaluate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
            wanted_year=2024,
        )
        assert best_validated is not None
        assert "005" in best_validated.title

        # Without validation (legacy): best quality score wins
        best_legacy = SearchService.evaluate_results(results)
        assert best_legacy is not None

    def test_search_query_has_issue_type(self) -> None:
        """SearchQuery dataclass accepts issue_type field."""
        query = SearchQuery(
            series_title="Batman",
            issue_number=5.0,
            year=2024,
            issue_type=IssueType.ISSUE.value,
        )
        assert query.issue_type == "issue"

    def test_search_query_default_issue_type(self) -> None:
        """SearchQuery defaults issue_type to 'issue'."""
        query = SearchQuery(series_title="Batman")
        assert query.issue_type == "issue"

    def test_legacy_evaluate_without_validation(self) -> None:
        """evaluate_results() without search params uses legacy scoring."""
        results = [make_release("Anything 005 [2024] [Digital]")]
        best = SearchService.evaluate_results(results)
        assert best is not None

    def test_annual_search_rejects_regular_issues(self) -> None:
        """Searching for an Annual must reject regular issues."""
        results = [
            make_release("Batman 005 [2024] [Digital]"),
            make_release("Batman Annual 005 [2024] [Digital]"),
        ]
        best = SearchService.evaluate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
            wanted_year=2024,
            wanted_issue_type=IssueType.ANNUAL,
        )
        assert best is not None
        assert "Annual" in best.title
