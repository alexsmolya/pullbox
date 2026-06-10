"""Tests for Phase E scoring functions.

Covers E-1 through E-5: grab count, pack penalty, language filter,
digital bonus, and file count threshold.

Run:
    pytest tests/unit/test_scoring_phase_e.py -v
"""

from __future__ import annotations

from pullbox.providers.base import ReleaseResult
from pullbox.services.search_service import (
    _score_digital_bonus,
    _score_grabs,
    _score_language,
    _score_pack_penalty,
    score_release,
)


def _make_release(**overrides: object) -> ReleaseResult:
    """Factory for ReleaseResult with sensible defaults."""
    defaults: dict[str, object] = {
        "title": "Batman (2016) #50 (Digital) (Zone-Empire).cbz",
        "indexer_name": "NZBgeek",
        "download_url": "https://example.com/nzb/123",
        "size_bytes": 100_000_000,
        "age_days": 30,
        "seeders": None,
        "leechers": None,
        "grabs": 50,
        "is_torrent": False,
        "category": "7020",
        "published_at": None,
        "info_url": None,
    }
    defaults.update(overrides)
    return ReleaseResult(**defaults)  # type: ignore[arg-type]


# ── E-1: Grab Count Scoring ──────────────────────────────────────────


class TestScoreGrabs:
    """E-1: _score_grabs() tiered scoring."""

    def test_none_grabs_returns_neutral(self) -> None:
        assert _score_grabs(None) == 30.0

    def test_zero_grabs(self) -> None:
        assert _score_grabs(0) == 30.0

    def test_low_grabs_1(self) -> None:
        assert _score_grabs(1) == 60.0

    def test_low_grabs_10(self) -> None:
        assert _score_grabs(10) == 60.0

    def test_medium_grabs_11(self) -> None:
        assert _score_grabs(11) == 80.0

    def test_medium_grabs_50(self) -> None:
        assert _score_grabs(50) == 80.0

    def test_high_grabs_51(self) -> None:
        assert _score_grabs(51) == 90.0

    def test_high_grabs_100(self) -> None:
        assert _score_grabs(100) == 90.0

    def test_very_high_grabs_101(self) -> None:
        assert _score_grabs(101) == 100.0

    def test_very_high_grabs_1000(self) -> None:
        assert _score_grabs(1000) == 100.0

    def test_negative_grabs_treated_as_zero(self) -> None:
        assert _score_grabs(-5) == 30.0


class TestGrabsIntegration:
    """E-1: grab weight integrates into score_release when enabled."""

    def test_grabs_weight_zero_has_no_effect(self) -> None:
        """Default weight 0 means grabs don't change the score."""
        release = _make_release(grabs=100)
        score_without = score_release(release)
        score_with = score_release(release, grabs_weight=0)
        assert score_without == score_with

    def test_grabs_weight_positive_affects_score(self) -> None:
        """Non-zero weight means grabs contribute to the final score."""
        high_grabs = _make_release(grabs=200)
        low_grabs = _make_release(grabs=0)
        # With grab weight enabled, high grabs should score higher
        score_high = score_release(high_grabs, grabs_weight=20)
        score_low = score_release(low_grabs, grabs_weight=20)
        assert score_high > score_low

    def test_weights_renormalize_with_grabs(self) -> None:
        """Adding grab weight re-normalizes all weights to sum to 1.0."""
        release = _make_release(grabs=50)
        # With all equal weights (20 each for 5 factors), each is 0.2
        score = score_release(
            release,
            score_weights=(20, 20, 20, 20),
            grabs_weight=20,
        )
        # Score should be a valid positive number
        assert score > 0


# ── E-2: Pack Penalty ────────────────────────────────────────────────


class TestScorePackPenalty:
    """E-2: _score_pack_penalty() detection and penalty."""

    def test_single_issue_no_penalty(self) -> None:
        assert _score_pack_penalty("Batman (2016) #50.cbz", file_count=1) == 0.0

    def test_pack_keyword_in_title(self) -> None:
        penalty = _score_pack_penalty("Batman (2016) #01-50 Pack.cbz", file_count=1, penalty=-20)
        assert penalty == -20.0

    def test_high_file_count_triggers_penalty(self) -> None:
        penalty = _score_pack_penalty(
            "Batman (2016) #50.cbz", file_count=10, max_file_count=5, penalty=-20
        )
        assert penalty == -20.0

    def test_file_count_at_threshold_no_penalty(self) -> None:
        penalty = _score_pack_penalty("Batman (2016) #50.cbz", file_count=5, max_file_count=5)
        assert penalty == 0.0

    def test_none_file_count_no_penalty(self) -> None:
        assert _score_pack_penalty("Batman (2016) #50.cbz", file_count=None) == 0.0

    def test_penalty_zero_disables(self) -> None:
        penalty = _score_pack_penalty("Batman (2016) #01-50 Pack.cbz", file_count=50, penalty=0)
        assert penalty == 0.0

    def test_issue_range_detected_as_pack(self) -> None:
        penalty = _score_pack_penalty("Batman 001-025 (2016).cbz", file_count=1, penalty=-20)
        assert penalty == -20.0

    def test_collection_keyword_detected_as_pack(self) -> None:
        penalty = _score_pack_penalty(
            "Batman Complete Collection (2016).cbz", file_count=1, penalty=-20
        )
        assert penalty == -20.0

    def test_omnibus_not_detected_as_pack(self) -> None:
        """Omnibus is a single volume, not a pack."""
        penalty = _score_pack_penalty("Batman Omnibus Vol 1 (2016).cbz", file_count=1)
        assert penalty == 0.0

    def test_negative_file_count_no_penalty(self) -> None:
        assert _score_pack_penalty("Batman #50.cbz", file_count=-1) == 0.0


# ── E-3: Language Filter ─────────────────────────────────────────────


class TestScoreLanguage:
    """E-3: _score_language() preference matching."""

    def test_english_title_english_pref_no_penalty(self) -> None:
        """No language marker → assumed English → no penalty."""
        assert _score_language("Batman (2016) #50.cbz", preferred="en") == 0.0

    def test_french_title_english_pref_penalized(self) -> None:
        score = _score_language("Batman (2016) #50 FRENCH.cbz", preferred="en")
        assert score < 0

    def test_french_title_french_pref_no_penalty(self) -> None:
        assert _score_language("Batman (2016) #50 FRENCH.cbz", preferred="fr") == 0.0

    def test_german_title_english_pref_penalized(self) -> None:
        score = _score_language("Batman (2016) #50 GERMAN.cbz", preferred="en")
        assert score < 0

    def test_spanish_title_english_pref_penalized(self) -> None:
        score = _score_language("Batman (2016) #50 SPANISH.cbz", preferred="en")
        assert score < 0

    def test_italian_title_english_pref_penalized(self) -> None:
        score = _score_language("Batman #50 ITALIAN.cbz", preferred="en")
        assert score < 0

    def test_japanese_title_english_pref_penalized(self) -> None:
        score = _score_language("Batman #50 JAPANESE.cbz", preferred="en")
        assert score < 0

    def test_case_insensitive_detection(self) -> None:
        score = _score_language("Batman #50 french.cbz", preferred="en")
        assert score < 0

    def test_no_language_marker_non_english_pref_no_penalty(self) -> None:
        """No marker → assumed English → no penalty even for non-English pref."""
        assert _score_language("Batman (2016) #50.cbz", preferred="fr") == 0.0

    def test_portuguese_title_english_pref_penalized(self) -> None:
        score = _score_language("Batman #50 PORTUGUESE.cbz", preferred="en")
        assert score < 0

    def test_korean_title_english_pref_penalized(self) -> None:
        score = _score_language("Batman #50 KOREAN.cbz", preferred="en")
        assert score < 0

    def test_dutch_title_english_pref_penalized(self) -> None:
        score = _score_language("Batman #50 DUTCH.cbz", preferred="en")
        assert score < 0

    def test_russian_title_english_pref_penalized(self) -> None:
        score = _score_language("Batman #50 RUSSIAN.cbz", preferred="en")
        assert score < 0

    def test_polish_title_english_pref_penalized(self) -> None:
        score = _score_language("Batman #50 POLISH.cbz", preferred="en")
        assert score < 0

    def test_chinese_title_english_pref_penalized(self) -> None:
        score = _score_language("Batman #50 CHINESE.cbz", preferred="en")
        assert score < 0

    def test_spanish_title_spanish_pref_no_penalty(self) -> None:
        assert _score_language("Batman #50 SPANISH.cbz", preferred="es") == 0.0


# ── E-4: Digital Quality Bonus ───────────────────────────────────────


class TestScoreDigitalBonus:
    """E-4: _score_digital_bonus() detection."""

    def test_digital_tag_gets_bonus(self) -> None:
        assert _score_digital_bonus("Batman #50 (Digital) (Zone-Empire).cbz", bonus=10) == 10.0

    def test_webrip_tag_gets_bonus(self) -> None:
        assert _score_digital_bonus("Batman #50 (Webrip).cbz", bonus=10) == 10.0

    def test_scan_tag_no_bonus(self) -> None:
        assert _score_digital_bonus("Batman #50 (scan).cbz", bonus=10) == 0.0

    def test_c2c_tag_no_bonus(self) -> None:
        assert _score_digital_bonus("Batman #50 (c2c).cbz", bonus=10) == 0.0

    def test_no_quality_tag_neutral(self) -> None:
        assert _score_digital_bonus("Batman #50.cbz", bonus=10) == 0.0

    def test_bonus_zero_disables(self) -> None:
        assert _score_digital_bonus("Batman #50 (Digital).cbz", bonus=0) == 0.0

    def test_case_insensitive_digital(self) -> None:
        assert _score_digital_bonus("Batman #50 DIGITAL.cbz", bonus=10) == 10.0

    def test_case_insensitive_webrip(self) -> None:
        assert _score_digital_bonus("Batman #50 WEBRIP.cbz", bonus=10) == 10.0

    def test_digital_in_group_name_gets_bonus(self) -> None:
        """Digital as part of group name like 'Digital-Empire' should still match."""
        assert _score_digital_bonus("Batman #50 (Digital-Empire).cbz", bonus=10) == 10.0

    def test_both_digital_and_scan_prefers_scan(self) -> None:
        """If both markers present, scan takes precedence (lower quality indicator)."""
        assert _score_digital_bonus("Batman #50 (Digital) (scan).cbz", bonus=10) == 0.0
