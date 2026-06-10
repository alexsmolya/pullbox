"""Integration tests for the MatchingService refactor.

Verifies that the refactored matching_service.py uses NameMatcher and
parse_release_title correctly, and IssueType routing sends non-standard types
to variant suggestion.

Run:
    pytest tests/integration/test_matching_refactor.py -v
"""

from pullbox.core.name_matcher import NameMatcher
from pullbox.models.issue import IssueType
from pullbox.models.library import MatchConfidence
from pullbox.services.matching_service import _confidence_from_match


class TestNameMatcherContract:
    """NameMatcher owns series normalization and similarity behavior."""

    def test_normalize_basic_cases(self) -> None:
        """Basic normalization produces lowercase stripped results."""
        cases = [
            ("Batman", "batman"),
            ("The Amazing Spider-Man", "amazing spider man"),
            ("Batman/Superman", "batman superman"),
            ("Batman    Superman", "batman superman"),
        ]
        for raw, expected in cases:
            assert NameMatcher.normalize(raw) == expected

    def test_similarity_uses_name_matcher(self) -> None:
        """NameMatcher.match() exposes the series similarity ratio."""
        matcher = NameMatcher()
        pairs = [
            ("Batman", "Batman", 1.0),
            ("The Amazing Spider-Man", "Amazing Spider-Man", 1.0),
        ]
        for parsed, target, expected in pairs:
            assert matcher.match(parsed, target).similarity == expected

    def test_similarity_different_names_do_not_match(self) -> None:
        """Very different names remain below the match threshold."""
        matcher = NameMatcher()
        result = matcher.match("Batman", "Superman")
        assert result.is_match is False
        assert result.similarity < 0.5


class TestConfidenceFromMatch:
    """Tests for the _confidence_from_match helper."""

    def test_exact_with_year_is_high(self) -> None:
        assert _confidence_from_match("exact", 1.0, 2024, 2024) == MatchConfidence.HIGH

    def test_exact_without_year_is_medium(self) -> None:
        assert _confidence_from_match("exact", 1.0, None, 2024) == MatchConfidence.MEDIUM

    def test_exact_with_close_year_is_high(self) -> None:
        assert _confidence_from_match("exact", 1.0, 2023, 2024) == MatchConfidence.HIGH

    def test_alternate_with_year_is_high(self) -> None:
        assert _confidence_from_match("alternate", 1.0, 2024, 2024) == MatchConfidence.HIGH

    def test_token_set_is_medium(self) -> None:
        assert _confidence_from_match("token_set", 0.90, 2024, 2024) == MatchConfidence.MEDIUM

    def test_token_set_no_year_is_medium(self) -> None:
        assert _confidence_from_match("token_set", 0.90, None, None) == MatchConfidence.MEDIUM

    def test_fuzzy_high_with_year_is_medium(self) -> None:
        assert _confidence_from_match("fuzzy", 0.90, 2024, 2024) == MatchConfidence.MEDIUM

    def test_fuzzy_high_no_year_is_low(self) -> None:
        assert _confidence_from_match("fuzzy", 0.90, None, None) == MatchConfidence.LOW

    def test_fuzzy_low_is_low(self) -> None:
        assert _confidence_from_match("fuzzy", 0.75, 2024, 2024) == MatchConfidence.LOW


class TestIssueTypeRouting:
    """Verify IssueType routing logic in the refactored service."""

    def test_tpb_detected_from_filename(self) -> None:
        """A TPB filename should be parsed with TPB issue_type."""
        from pullbox.core.release_parser import parse_release_title

        parsed = parse_release_title("Batman TPB Vol 3.cbz")
        assert parsed is not None
        assert parsed.issue_type == IssueType.TPB

    def test_annual_detected_from_filename(self) -> None:
        """An Annual filename should be parsed with ANNUAL issue_type."""
        from pullbox.core.release_parser import parse_release_title

        parsed = parse_release_title("Batman Annual 005 [2024] [Digital]")
        assert parsed is not None
        assert parsed.issue_type == IssueType.ANNUAL

    def test_omnibus_detected_from_filename(self) -> None:
        """An Omnibus filename should be parsed with OMNIBUS issue_type."""
        from pullbox.core.release_parser import parse_release_title

        parsed = parse_release_title("Batman Omnibus Vol 1 [2024]")
        assert parsed is not None
        assert parsed.issue_type == IssueType.OMNIBUS

    def test_regular_issue_is_issue_type(self) -> None:
        """A standard issue filename should parse as ISSUE type."""
        from pullbox.core.release_parser import parse_release_title

        parsed = parse_release_title("Batman 005 [2024] [Digital]")
        assert parsed is not None
        assert parsed.issue_type == IssueType.ISSUE


class TestNameMatcherIntegration:
    """Verify NameMatcher is used consistently across matching paths."""

    def test_html_entities_normalized(self) -> None:
        """NameMatcher handles HTML entities that NZB titles contain."""
        assert NameMatcher.normalize("Batman &amp; Superman") == NameMatcher.normalize(
            "Batman & Superman"
        )

    def test_smart_quotes_normalized(self) -> None:
        """NameMatcher handles smart quotes/apostrophes."""
        result = NameMatcher.normalize("World\u2019s Finest")
        assert "worlds" in result

    def test_unicode_dashes_normalized(self) -> None:
        """NameMatcher handles unicode dashes."""
        result = NameMatcher.normalize("Spider\u2013Man")
        assert result == NameMatcher.normalize("Spider-Man")


class TestAlternateSeriesNames:
    """Verify alternate_names wiring through NameMatcher and ReleaseValidator."""

    def test_name_matcher_exact_alternate(self) -> None:
        """NameMatcher matches an alternate name with 'alternate' match_type."""
        matcher = NameMatcher()
        result = matcher.match("TMNT", "Teenage Mutant Ninja Turtles", alternate_names=["TMNT"])
        assert result.is_match
        assert result.match_type == "alternate"
        assert result.similarity == 1.0

    def test_name_matcher_no_alternate_no_match(self) -> None:
        """Without alternate_names, abbreviation doesn't match the full title."""
        matcher = NameMatcher()
        result = matcher.match("TMNT", "Teenage Mutant Ninja Turtles")
        assert not result.is_match

    def test_name_matcher_alternate_normalized(self) -> None:
        """Alternate names are normalized before comparison."""
        matcher = NameMatcher()
        result = matcher.match("tmnt", "Teenage Mutant Ninja Turtles", alternate_names=["TMNT"])
        assert result.is_match
        assert result.match_type == "alternate"

    def test_release_validator_uses_alternate_names(self) -> None:
        """ReleaseValidator passes alternate_names to NameMatcher for matching."""
        from pullbox.services.release_validator import ReleaseValidator
        from tests.conftest import make_release

        release = make_release("TMNT 005 (2024) (Digital).cbz")
        validator = ReleaseValidator()

        # Without alternate names, "TMNT" shouldn't match "Teenage Mutant Ninja Turtles"
        rejected = validator.validate_results(
            [release],
            wanted_series="Teenage Mutant Ninja Turtles",
            wanted_issue=5.0,
            wanted_year=2024,
        )
        assert len(rejected) == 0

        # With alternate names, it should match
        accepted = validator.validate_results(
            [release],
            wanted_series="Teenage Mutant Ninja Turtles",
            wanted_issue=5.0,
            wanted_year=2024,
            alternate_names=["TMNT"],
        )
        assert len(accepted) == 1
        assert accepted[0].is_match
        assert accepted[0].series_similarity == 1.0

    def test_evaluate_results_with_alternate_names(self) -> None:
        """SearchService.evaluate_results passes alternate_names through."""
        from pullbox.services.search_service import SearchService
        from tests.conftest import make_release

        release = make_release("TMNT 005 (2024) (Digital).cbz")

        # Without alternate names — no match
        result_none = SearchService.evaluate_results(
            [release],
            wanted_series="Teenage Mutant Ninja Turtles",
            wanted_issue=5.0,
            wanted_year=2024,
        )
        assert result_none is None

        # With alternate names — should find a match
        result_alt = SearchService.evaluate_results(
            [release],
            wanted_series="Teenage Mutant Ninja Turtles",
            wanted_issue=5.0,
            wanted_year=2024,
            alternate_names=["TMNT"],
        )
        assert result_alt is not None
        assert result_alt.title == release.title
