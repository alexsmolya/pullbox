"""Unit tests for the release validation service.

Covers bug regressions, confidence gradation, ignore words, and edge cases.

Run:
    pytest tests/unit/test_release_validator.py -v
    pytest tests/unit/test_release_validator.py -k "regression" -v
"""

import pytest

from pullbox.models.issue import IssueType
from pullbox.models.library import MatchConfidence
from pullbox.services.release_validator import ReleaseValidator
from tests.conftest import make_release


class TestBugRegressions:
    """Non-negotiable. These are the bugs we're fixing."""

    def setup_method(self) -> None:
        self.validator = ReleaseValidator()

    @pytest.mark.regression
    def test_wrong_issue_rejected(self) -> None:
        """Bug #1: Batman #5 search must NOT return Batman #50."""
        results = [make_release("Batman 050 [2024] [Digital] [Shan-Empire]")]
        validated = self.validator.validate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
            wanted_year=2024,
        )
        assert len(validated) == 0

    @pytest.mark.regression
    def test_tpb_rejected_for_issue_search(self) -> None:
        """Bug #2: Search for issue #5 must NOT return TPB Vol 5."""
        results = [make_release("Batman TPB Vol 5 [2024] [Digital]")]
        validated = self.validator.validate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
            wanted_issue_type=IssueType.ISSUE,
        )
        assert len(validated) == 0

    @pytest.mark.regression
    def test_annual_rejected_for_issue_search(self) -> None:
        """Bug #3: Search for issue #5 must NOT return Annual #5."""
        results = [make_release("Batman Annual 005 [2024] [Digital]")]
        validated = self.validator.validate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
            wanted_issue_type=IssueType.ISSUE,
        )
        assert len(validated) == 0

    @pytest.mark.regression
    def test_correct_match_accepted(self) -> None:
        """Batman #5 search SHOULD return 'Batman 005 [2024] [Digital]'."""
        results = [make_release("Batman 005 [2024] [Digital] [Shan-Empire]")]
        validated = self.validator.validate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
            wanted_year=2024,
        )
        assert len(validated) == 1
        assert validated[0].is_match is True
        assert validated[0].confidence == MatchConfidence.HIGH

    @pytest.mark.regression
    def test_publisher_prefixed_volume_subtitle_release_is_accepted(self) -> None:
        """Publisher-prefixed NZBGeek volumes should not fail series matching."""
        results = [
            make_release(
                "Image.Comics-Drifter.Vol.01.Out.Of.The.Night.2015.Retail.Comic.eBook-BitBook"
            )
        ]

        validated = self.validator.validate_results(
            results,
            wanted_series="Drifter: Out of the Night",
            wanted_issue=1.0,
            wanted_year=2015,
            wanted_issue_type=IssueType.VOLUME,
        )

        assert len(validated) == 1
        assert validated[0].is_match is True

    @pytest.mark.regression
    def test_wrong_series_rejected(self) -> None:
        """Bug #7: Batman #5 search must NOT return Superman #5."""
        results = [make_release("Superman 005 [2024] [Digital]")]
        validated = self.validator.validate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
        )
        assert len(validated) == 0

    @pytest.mark.regression
    def test_cover_only_rejected(self) -> None:
        """Bug #5: Cover-only releases must be rejected."""
        validator = ReleaseValidator(ignore_words=["covers only", "cover only"])
        results = [make_release("Batman 005 [2024] COVERS ONLY [Digital]")]
        validated = validator.validate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
        )
        assert len(validated) == 0


class TestConfidenceGradation:
    """Tests for confidence level assignment."""

    def setup_method(self) -> None:
        self.validator = ReleaseValidator()

    def test_exact_series_exact_issue_year_match_is_high(self) -> None:
        results = [make_release("Batman 005 [2024] [Digital]")]
        validated = self.validator.validate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
            wanted_year=2024,
        )
        assert len(validated) == 1
        assert validated[0].confidence == MatchConfidence.HIGH

    def test_exact_series_exact_issue_no_year_is_medium(self) -> None:
        results = [make_release("Batman 005 [Digital]")]
        validated = self.validator.validate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
            wanted_year=2024,
        )
        assert len(validated) == 1
        assert validated[0].confidence == MatchConfidence.MEDIUM

    def test_fuzzy_series_match_is_low(self) -> None:
        """A name in the 0.70-0.85 fuzzy range should get LOW confidence."""
        results = [make_release("Batmaniac 005 [2024] [Digital]")]
        validated = self.validator.validate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
            wanted_year=2024,
        )
        if len(validated) > 0:
            assert validated[0].confidence == MatchConfidence.LOW

    def test_multiple_valid_sorted_by_confidence(self) -> None:
        results = [
            make_release("Batman 005 [Digital]"),
            make_release("Batman 005 [2024] [Digital]"),
        ]
        validated = self.validator.validate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
            wanted_year=2024,
        )
        assert len(validated) == 2
        assert validated[0].confidence == MatchConfidence.HIGH

    def test_wrong_year_is_low(self) -> None:
        results = [make_release("Batman 005 [2018] [Digital]")]
        validated = self.validator.validate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
            wanted_year=2024,
        )
        assert len(validated) == 1
        assert validated[0].confidence == MatchConfidence.LOW

    def test_alternate_name_with_year_is_high(self) -> None:
        results = [make_release("TMNT 005 [2024] [Digital]")]
        validated = self.validator.validate_results(
            results,
            wanted_series="Teenage Mutant Ninja Turtles",
            wanted_issue=5.0,
            wanted_year=2024,
            alternate_names=["TMNT"],
        )
        assert len(validated) == 1
        assert validated[0].confidence == MatchConfidence.HIGH

    def test_collection_volume_number_match_is_accepted(self) -> None:
        results = [make_release("Batman TPB Vol 5 [2024] [Digital]")]
        validated = self.validator.validate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
            wanted_year=2024,
            wanted_issue_type=IssueType.TPB,
        )
        assert len(validated) == 1
        assert validated[0].confidence in (MatchConfidence.HIGH, MatchConfidence.MEDIUM)

    def test_collection_subtitle_match_is_accepted(self) -> None:
        results = [make_release("Immortal Thor All Weather Turns To Storm [2024] [Digital]")]
        validated = self.validator.validate_results(
            results,
            wanted_series="Immortal Thor",
            wanted_issue=1.0,
            wanted_year=2024,
            wanted_issue_type=IssueType.TPB,
        )
        assert len(validated) == 1
        assert validated[0].is_match is True


class TestIgnoreWords:
    """Tests for ignore word filtering."""

    def test_phrase_match_rejected(self) -> None:
        validator = ReleaseValidator(ignore_words=["covers only"])
        results = [make_release("Batman 005 COVERS ONLY [2024]")]
        validated = validator.validate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
        )
        assert len(validated) == 0

    def test_substring_not_rejected(self) -> None:
        """'covers' alone should NOT match 'covers only' rule."""
        validator = ReleaseValidator(ignore_words=["covers only"])
        results = [make_release("Batman 005 [2024] [4 covers] [Digital]")]
        validated = validator.validate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
        )
        assert len(validated) >= 1

    def test_case_insensitive(self) -> None:
        validator = ReleaseValidator(ignore_words=["preview"])
        results = [make_release("Batman 005 PREVIEW [2024]")]
        validated = validator.validate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
        )
        assert len(validated) == 0

    def test_multiple_ignore_words(self) -> None:
        validator = ReleaseValidator(ignore_words=["covers only", "preview", "ashcan"])
        results = [
            make_release("Batman 005 [2024] [Digital]"),
            make_release("Batman 005 PREVIEW [2024]"),
            make_release("Batman 005 ashcan [2024]"),
        ]
        validated = validator.validate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
        )
        assert len(validated) == 1

    def test_default_ignore_words_used(self) -> None:
        """Default ignore words should be active when none specified."""
        validator = ReleaseValidator()
        results = [make_release("Batman 005 [2024] COVERS ONLY [Digital]")]
        validated = validator.validate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
        )
        assert len(validated) == 0


class TestValidatorEdgeCases:
    """Edge case and boundary tests."""

    def setup_method(self) -> None:
        self.validator = ReleaseValidator()

    def test_empty_results_returns_empty(self) -> None:
        validated = self.validator.validate_results(
            [],
            wanted_series="Batman",
            wanted_issue=5.0,
        )
        assert validated == []

    def test_all_rejected_returns_empty(self) -> None:
        results = [
            make_release("Superman 005 [2024]"),
            make_release("Batman 050 [2024]"),
            make_release("Batman Annual 005 [2024]"),
        ]
        validated = self.validator.validate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
            wanted_issue_type=IssueType.ISSUE,
        )
        assert validated == []

    def test_year_tolerance_within_one(self) -> None:
        results = [make_release("Batman 005 [2023] [Digital]")]
        validated = self.validator.validate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
            wanted_year=2024,
        )
        assert len(validated) >= 1

    def test_year_tolerance_outside_range(self) -> None:
        results = [make_release("Batman 005 [2020] [Digital]")]
        validated = self.validator.validate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
            wanted_year=2024,
        )
        if len(validated) > 0:
            assert validated[0].confidence in (MatchConfidence.LOW, MatchConfidence.MEDIUM)

    def test_unparseable_title_rejected(self) -> None:
        results = [make_release("")]
        validated = self.validator.validate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
        )
        assert len(validated) == 0

    def test_validation_result_fields_populated(self) -> None:
        results = [make_release("Batman 005 [2024] [Digital] [Shan-Empire]")]
        validated = self.validator.validate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
            wanted_year=2024,
        )
        assert len(validated) == 1
        vr = validated[0]
        assert vr.series_similarity == 1.0
        assert vr.issue_match is True
        assert vr.year_match is True
        assert vr.issue_type_match is True
        assert vr.rejection_reason is None

    def test_rejection_has_reason(self) -> None:
        """Rejected results from _validate_one include a reason string."""
        validator = ReleaseValidator(ignore_words=["preview"])
        results = [make_release("Batman 005 PREVIEW [2024]")]
        # Call _validate_one directly to inspect the rejection
        vr = validator._validate_one(
            results[0],
            wanted_series="Batman",
            wanted_issue=5.0,
            wanted_year=2024,
            wanted_issue_type=IssueType.ISSUE,
            alternate_names=None,
        )
        assert vr.is_match is False
        assert vr.rejection_reason is not None
        assert "ignore word" in vr.rejection_reason.lower()


class TestIgnoreWordsConfig:
    """Tests for configurable ignore words wiring."""

    def test_default_ignore_words_loaded(self) -> None:
        """DEFAULT_IGNORE_WORDS contains the expected phrases."""
        from pullbox.services.release_validator import DEFAULT_IGNORE_WORDS

        assert "covers only" in DEFAULT_IGNORE_WORDS
        assert "preview" in DEFAULT_IGNORE_WORDS
        assert "ashcan" in DEFAULT_IGNORE_WORDS
        assert "blank cover" in DEFAULT_IGNORE_WORDS
        assert "sampler" in DEFAULT_IGNORE_WORDS

    def test_custom_ignore_words_override(self) -> None:
        """Custom ignore_words replaces defaults — 'preview' not rejected."""
        validator = ReleaseValidator(ignore_words=["custom phrase"])
        # Use bracketed tag so "PREVIEW" doesn't pollute parsed series name
        results = [make_release("Batman 005 [2024] [PREVIEW]")]
        validated = validator.validate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
            wanted_year=2024,
        )
        # "preview" NOT in custom list — should NOT be rejected by ignore filter
        assert len(validated) >= 1

    def test_custom_ignore_words_rejects_custom_phrase(self) -> None:
        """Custom phrase is enforced when provided."""
        validator = ReleaseValidator(ignore_words=["digital exclusive"])
        results = [make_release("Batman 005 [2024] [Digital Exclusive]")]
        validated = validator.validate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
        )
        assert len(validated) == 0

    def test_empty_ignore_words_disables_filtering(self) -> None:
        """Empty list means no ignore word filtering at all."""
        validator = ReleaseValidator(ignore_words=[])
        # Use bracketed tag so "COVERS ONLY" doesn't pollute parsed series name
        results = [make_release("Batman 005 [2024] [COVERS ONLY]")]
        validated = validator.validate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
            wanted_year=2024,
        )
        assert len(validated) >= 1

    def test_search_ignore_words_in_system_config(self) -> None:
        """search_ignore_words exists in DEFAULT_SYSTEM_CONFIG."""
        from pullbox.models.config import DEFAULT_SYSTEM_CONFIG

        assert "search_ignore_words" in DEFAULT_SYSTEM_CONFIG
        value, value_type = DEFAULT_SYSTEM_CONFIG["search_ignore_words"]
        assert value_type == "string"
        assert "covers only" in value
        assert "preview" in value

    def test_config_value_parses_to_list(self) -> None:
        """The comma-separated config value parses into the expected list."""
        from pullbox.models.config import DEFAULT_SYSTEM_CONFIG

        value, _ = DEFAULT_SYSTEM_CONFIG["search_ignore_words"]
        words = [w.strip() for w in value.split(",") if w.strip()]
        assert "covers only" in words
        assert "cover only" in words
        assert "preview" in words
        assert "ashcan" in words
        assert "blank cover" in words
        assert len(words) == 11

    def test_evaluate_results_passes_ignore_words(self) -> None:
        """SearchService.evaluate_results forwards ignore_words to validator."""
        from pullbox.services.search_service import SearchService

        # Use bracketed tag so "PREVIEW" doesn't pollute parsed series name
        results = [make_release("Batman 005 [2024] [PREVIEW]")]

        # With default ignore words — preview should be rejected
        best_default = SearchService.evaluate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
            wanted_year=2024,
        )
        assert best_default is None

        # With custom ignore words that don't include "preview" — should pass
        best_custom = SearchService.evaluate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
            wanted_year=2024,
            ignore_words=["custom only"],
        )
        assert best_custom is not None


class TestTypeKeywordConfidenceFix:
    """Tests for the confidence fix when DB series title contains type keywords."""

    def setup_method(self) -> None:
        self.validator = ReleaseValidator()

    def test_series_with_type_keyword_gets_good_confidence(self) -> None:
        """Series 'Black Science Compendium' with release parsed to 'Black Science'.

        The release parser strips 'Compendium' from the parsed title, leaving
        'Black Science' vs wanted 'Black Science Compendium'.  The stripped
        retry should match 'Black Science' vs 'Black Science' (exact) and
        produce MEDIUM+ confidence, not LOW.
        """
        results = [make_release("Black Science Compendium [2024] [Digital]", size_mb=200)]
        validated = self.validator.validate_results(
            results,
            wanted_series="Black Science Compendium",
            wanted_issue=1.0,
            wanted_year=2024,
            wanted_issue_type=IssueType.COMPENDIUM,
        )
        assert len(validated) >= 1
        # Should be MEDIUM or HIGH, not LOW
        assert validated[0].confidence in (MatchConfidence.HIGH, MatchConfidence.MEDIUM)

    def test_providence_compendium_confidence(self) -> None:
        """Providence Compendium — same pattern, verifies not LOW."""
        results = [make_release("Providence Compendium [2024] [Digital]", size_mb=200)]
        validated = self.validator.validate_results(
            results,
            wanted_series="Providence Compendium",
            wanted_issue=1.0,
            wanted_year=2024,
            wanted_issue_type=IssueType.COMPENDIUM,
        )
        assert len(validated) >= 1
        assert validated[0].confidence in (MatchConfidence.HIGH, MatchConfidence.MEDIUM)
