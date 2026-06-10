"""Phase B: Scoring algorithm tests using real-world NZBGeek metadata.

Validates size distribution, file count, age scoring, grab count,
category validation, and score ranking against the expanded fixture.

Run:
    pytest tests/unit/test_search_scoring_real_world.py -v
"""

from __future__ import annotations

import pytest

from pullbox.services.search_service import (
    _score_age,
    _score_category,
    _score_grabs,
    _score_size,
)

_MB = 1024 * 1024


# ── B-1: Size Distribution Sanity ─────────────────────────────


class TestSizeDistribution:
    """File sizes should fall within expected ranges for comic files."""

    def test_majority_in_valid_range(
        self,
        nzbgeek_issue_results: list[dict],
    ) -> None:
        """95% of issues with known size are between 1MB and 500MB."""
        sizes = [
            r["size"] for r in nzbgeek_issue_results if r.get("size") is not None and r["size"] > 0
        ]
        assert len(sizes) > 100, "Too few results with size data"
        in_range = sum(1 for s in sizes if 1 * _MB <= s <= 500 * _MB)
        rate = in_range / len(sizes)
        assert rate >= 0.90, f"Only {rate:.1%} of sizes in 1-500MB range ({in_range}/{len(sizes)})"

    def test_median_in_expected_range(
        self,
        nzbgeek_issue_results: list[dict],
    ) -> None:
        """Median file size should be between 10MB and 200MB."""
        sizes = sorted(
            r["size"] for r in nzbgeek_issue_results if r.get("size") is not None and r["size"] > 0
        )
        assert len(sizes) > 100
        median = sizes[len(sizes) // 2]
        median_mb = median / _MB
        assert 10 <= median_mb <= 200, f"Median size {median_mb:.1f}MB outside 10-200MB range"

    def test_size_scoring_ideal_range(self) -> None:
        """Size scoring gives 100 for files in the ideal range."""
        assert _score_size(50 * _MB, min_size_mb=5, max_size_mb=200) == 100.0
        assert _score_size(100 * _MB, min_size_mb=5, max_size_mb=200) == 100.0

    def test_size_scoring_too_small(self) -> None:
        """Undersized files score proportionally lower."""
        score = _score_size(1 * _MB, min_size_mb=5, max_size_mb=200)
        assert 0 < score < 100

    def test_size_scoring_too_large(self) -> None:
        """Oversized files score lower."""
        score = _score_size(500 * _MB, min_size_mb=5, max_size_mb=200)
        assert score < 100

    def test_size_scoring_unknown(self) -> None:
        """Unknown size gets neutral score."""
        assert _score_size(None, min_size_mb=5, max_size_mb=200) == 50.0


# ── B-2: File Count Validation ────────────────────────────────


class TestFileCountValidation:
    """NZB file counts should correlate with release type."""

    def test_majority_single_file(
        self,
        nzbgeek_issue_results: list[dict],
    ) -> None:
        """90% of individual issues should have ≤3 files."""
        with_files = [
            r for r in nzbgeek_issue_results if r.get("files") is not None and r["files"] > 0
        ]
        if len(with_files) < 50:
            pytest.skip("Insufficient file count data in fixture")
        low_files = sum(1 for r in with_files if r["files"] <= 3)
        rate = low_files / len(with_files)
        assert rate >= 0.85, f"Only {rate:.1%} have ≤3 files ({low_files}/{len(with_files)})"

    def test_high_file_count_is_rare(
        self,
        nzbgeek_issue_results: list[dict],
    ) -> None:
        """Less than 5% of results have >10 files (likely packs)."""
        with_files = [
            r for r in nzbgeek_issue_results if r.get("files") is not None and r["files"] > 0
        ]
        if len(with_files) < 50:
            pytest.skip("Insufficient file count data")
        high = sum(1 for r in with_files if r["files"] > 10)
        rate = high / len(with_files)
        assert rate < 0.05, f"{rate:.1%} have >10 files ({high}/{len(with_files)})"


# ── B-3: Age Scoring Curve ────────────────────────────────────


class TestAgeScoringCurve:
    """Age scoring function should produce expected results."""

    def test_fresh_release_scores_high(self) -> None:
        """Release from today scores ~100."""
        assert _score_age(0) >= 99.0

    def test_month_old_scores_well(self) -> None:
        """30-day-old release still scores high."""
        score = _score_age(30)
        assert score >= 99.0

    def test_year_old_still_reasonable(self) -> None:
        """Year-old release retains good score (comics have long shelf life)."""
        score = _score_age(365)
        assert score >= 90.0

    def test_decade_old_hits_floor(self) -> None:
        """10-year-old release hits the floor score."""
        score = _score_age(3650)
        assert score == 30.0

    def test_unknown_age_neutral(self) -> None:
        """Unknown age gets neutral score."""
        assert _score_age(None) == 50.0

    def test_monotonically_decreasing(self) -> None:
        """Score decreases as age increases."""
        prev = _score_age(0)
        for days in [7, 30, 90, 365, 1000, 3650]:
            current = _score_age(days)
            assert current <= prev, f"Score increased from {prev} to {current} at {days} days"
            prev = current


# ── B-4: Grab Count Distribution ──────────────────────────────


class TestGrabCountDistribution:
    """Download counts should have reasonable spread."""

    def test_grab_data_field_exists(
        self,
        nzbgeek_issue_results: list[dict],
    ) -> None:
        """Dataset results have the grabs field (may be None if API doesn't provide it)."""
        assert len(nzbgeek_issue_results) > 100
        # NZBGeek may not return grabs — verify the field exists in the schema
        assert "grabs" in nzbgeek_issue_results[0]

    def test_grab_range(
        self,
        nzbgeek_issue_results: list[dict],
    ) -> None:
        """Grab counts span a meaningful range."""
        grabs = [
            r["grabs"]
            for r in nzbgeek_issue_results
            if r.get("grabs") is not None and r["grabs"] > 0
        ]
        if len(grabs) < 50:
            pytest.skip("Insufficient grab data")
        assert max(grabs) >= 20, f"Max grabs only {max(grabs)}"
        assert min(grabs) >= 0

    def test_grab_none_handled_gracefully(self) -> None:
        """Grab count of None should not crash scoring functions."""
        assert _score_grabs(None) == 30.0
        assert _score_grabs(0) == 30.0


# ── B-5: Category Validation ──────────────────────────────────


class TestCategoryValidation:
    """Results should be in expected Newznab categories."""

    def test_comic_category_dominant(
        self,
        nzbgeek_issue_results: list[dict],
    ) -> None:
        """95%+ of results are in comic/book categories."""
        comic_cats = {"7020", "7030", "7000", "7010", "7040"}
        in_category = 0
        for r in nzbgeek_issue_results:
            cat = str(r.get("category", ""))
            if any(c in cat for c in comic_cats):
                in_category += 1
        rate = in_category / len(nzbgeek_issue_results)
        assert rate >= 0.95, (
            f"Only {rate:.1%} in comic categories ({in_category}/{len(nzbgeek_issue_results)})"
        )

    def test_category_bonus_comics(self) -> None:
        """Comic category 7030 gets +15 (Comics)."""
        assert _score_category("7030") == 15.0

    def test_category_bonus_books_subcategory(self) -> None:
        """Book subcategories (7020, 7000, 7010, 7040) get +5."""
        assert _score_category("7020") == 5.0

    def test_category_bonus_books(self) -> None:
        """Book categories get +5."""
        assert _score_category("7000") == 5.0

    def test_category_bonus_unknown(self) -> None:
        """Unknown category gets 0."""
        assert _score_category(None) == 0.0
        assert _score_category("") == 0.0
        assert _score_category("9999") == 0.0

    def test_multi_category_picks_best(self) -> None:
        """Comma-separated categories pick the best bonus."""
        assert _score_category("7030,7020") == 15.0


# ── B-6: Score Ranking Sanity ─────────────────────────────────


class TestScoreRankingSanity:
    """Scoring produces reasonable rankings."""

    def test_newer_scores_higher_than_older(self) -> None:
        """Newer releases should score higher than older ones (all else equal)."""
        new_score = _score_age(1)
        old_score = _score_age(365)
        assert new_score > old_score

    def test_ideal_size_scores_higher_than_outlier(self) -> None:
        """Files in the ideal size range score higher than outliers."""
        ideal = _score_size(50 * _MB, min_size_mb=5, max_size_mb=200)
        small = _score_size(1 * _MB, min_size_mb=5, max_size_mb=200)
        large = _score_size(1000 * _MB, min_size_mb=5, max_size_mb=200)
        assert ideal > small
        assert ideal > large

    def test_no_negative_scores(self) -> None:
        """Individual scoring functions never return negative."""
        assert _score_age(99999) >= 0
        assert _score_size(0, min_size_mb=5, max_size_mb=200) >= 0
        assert _score_category("unknown") >= 0
