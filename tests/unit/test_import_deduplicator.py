"""Unit tests for import series deduplication."""

from __future__ import annotations

from pullbox.core.collection_scanner import DiscoveredSeries
from pullbox.services.import_service import DeduplicationResult, _is_same_series


def _make_discovered(
    name: str = "Batman",
    year: int | None = 2016,
    publisher: str | None = None,
    file_count: int = 5,
    mylar3_cv_id: int | None = None,
    source_folder: str = "/comics/Batman (2016)",
) -> DiscoveredSeries:
    """Create a DiscoveredSeries for testing."""
    return DiscoveredSeries(
        raw_series_name=name,
        raw_year=year,
        raw_publisher=publisher,
        file_count=file_count,
        sample_paths=[],
        source_folder=source_folder,
        source_folder_relative=name,
        mylar3_cv_id=mylar3_cv_id,
    )


class TestIsSameSeries:
    """Test the _is_same_series comparison function."""

    def test_exact_title_and_year(self) -> None:
        assert _is_same_series("Batman", 2016, "Batman", 2016) is True

    def test_exact_title_year_off_by_one(self) -> None:
        assert _is_same_series("Batman", 2016, "Batman", 2017) is True

    def test_same_title_different_year(self) -> None:
        """Different volume/run should NOT be a duplicate."""
        assert _is_same_series("Batman", 2016, "Batman", 1940) is False

    def test_title_only_match_no_years(self) -> None:
        """Both years None — title-only match."""
        assert _is_same_series("Batman", None, "Batman", None) is True

    def test_candidate_year_none_existing_has_year(self) -> None:
        """Year missing on one side — title exact match still works."""
        assert _is_same_series("Batman", None, "Batman", 2016) is True

    def test_existing_year_none_candidate_has_year(self) -> None:
        assert _is_same_series("Batman", 2016, "Batman", None) is True

    def test_fuzzy_title_match(self) -> None:
        """Close but not exact title should match above threshold."""
        assert _is_same_series("The Batman", 2016, "Batman", 2016) is True

    def test_fuzzy_base_title_does_not_match_subtitle_spinoff(self) -> None:
        """Base-series imports should not dedupe onto subtitle/spinoff library series."""
        assert (
            _is_same_series(
                "Teenage Mutant Ninja Turtles",
                2024,
                "Teenage Mutant Ninja Turtles: Shredder",
                2025,
            )
            is False
        )

    def test_starts_with_base_title_does_not_match_subtitle_spinoff(self) -> None:
        """The same guard applies when the added subtitle has multiple words."""
        assert (
            _is_same_series(
                "Teenage Mutant Ninja Turtles",
                2024,
                "Teenage Mutant Ninja Turtles Saturday Morning Adventures",
                2024,
            )
            is False
        )

    def test_subtitle_import_does_not_match_existing_base_title(self) -> None:
        """More-specific import titles should stay reviewable instead of deduping to a base."""
        assert (
            _is_same_series(
                "Immortal Thor All Weather Turns To Storm",
                2024,
                "Immortal Thor",
                2024,
            )
            is False
        )

    def test_sampler_title_does_not_match_existing_base_title(self) -> None:
        """Anthology/sampler-style expanded titles should not attach to the base series."""
        assert (
            _is_same_series(
                "Seven Wives IDW Crime Sampler",
                2026,
                "Seven Wives",
                2026,
            )
            is False
        )

    def test_same_year_sibling_subtitle_one_shots_do_not_dedupe(self) -> None:
        """Shared long prefixes with different subtitle subjects are separate series."""
        assert (
            _is_same_series(
                "G.I. Joe - A Real American Hero Sssilent Missions - Firefly",
                2026,
                "G.I. Joe: A Real American Hero Sssilent Missions: Zartan",
                2026,
            )
            is False
        )

    def test_very_different_titles(self) -> None:
        assert _is_same_series("Saga", 2012, "Batman", 2016) is False

    def test_different_title_same_year(self) -> None:
        assert _is_same_series("Saga", 2012, "Batman", 2012) is False

    def test_high_similarity_year_missing_matches(self) -> None:
        """Very high similarity with missing year still matches."""
        assert _is_same_series("Batman", None, "Batman", 2000) is True

    def test_normalized_comparison(self) -> None:
        """Normalization strips articles, punctuation, etc."""
        assert _is_same_series("The Amazing Spider-Man", 2015, "Amazing Spider-Man", 2015) is True

    def test_custom_threshold(self) -> None:
        """Lower threshold allows fuzzier matches."""
        assert _is_same_series("Batmn", 2016, "Batman", 2016, similarity_threshold=0.70) is True

    def test_threshold_too_high_rejects(self) -> None:
        """Very high threshold rejects near-matches."""
        assert _is_same_series("Batmn", 2016, "Batman", 2016, similarity_threshold=0.99) is False


class TestDeduplicationResult:
    """Test DeduplicationResult dataclass."""

    def test_new_series(self) -> None:
        d = _make_discovered()
        result = DeduplicationResult(discovered=d, is_duplicate=False)
        assert result.is_duplicate is False
        assert result.existing_series_id is None
        assert result.existing_series_title is None

    def test_duplicate_series(self) -> None:
        d = _make_discovered()
        result = DeduplicationResult(
            discovered=d,
            is_duplicate=True,
            existing_series_id=42,
            existing_series_title="Batman",
        )
        assert result.is_duplicate is True
        assert result.existing_series_id == 42
        assert result.existing_series_title == "Batman"
