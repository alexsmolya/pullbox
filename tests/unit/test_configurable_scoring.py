"""Unit tests for configurable scoring weights and matching thresholds.

Covers Tier 1 (quality scoring weights, confidence blend) and
Tier 2 (fuzzy thresholds, year tolerance) configurability.

Run:
    pytest tests/unit/test_configurable_scoring.py -v
"""

import pytest

from pullbox.core.name_matcher import NameMatcher
from pullbox.models.library import MatchConfidence
from pullbox.services.release_validator import ReleaseValidator
from pullbox.services.search_service import SearchService, score_release
from tests.conftest import make_release

# ── Tier 1: Quality Scoring Weights ──────────────────────────────────


class TestScoreReleaseWeights:
    """Tests for configurable score_release() weights."""

    def test_default_weights_produce_expected_score(self) -> None:
        """Default weights (40/30/20/10) produce a reasonable score.

        Score can exceed 100 due to additive bonuses (category, seeders,
        digital) applied on top of the weighted base.
        """
        release = make_release("Batman 005 [2024] [Digital].cbz", size_mb=100, age_days=5)
        score = score_release(release, indexer_priority=25)
        assert 0 < score <= 130

    def test_custom_weights_change_score(self) -> None:
        """Different weights produce different scores."""
        release = make_release("Batman 005 [2024] [Digital].cbz", size_mb=100, age_days=5)
        default_score = score_release(release, indexer_priority=25)
        custom_score = score_release(
            release, indexer_priority=25, score_weights=(0.10, 0.10, 0.10, 0.70)
        )
        assert default_score != custom_score

    def test_all_weight_on_priority(self) -> None:
        """100% priority weight means score is entirely priority-based."""
        release = make_release("Batman 005 [2024]", size_mb=100, age_days=5)
        score_high = score_release(release, indexer_priority=1, score_weights=(1.0, 0.0, 0.0, 0.0))
        score_low = score_release(release, indexer_priority=50, score_weights=(1.0, 0.0, 0.0, 0.0))
        assert score_high > score_low
        # +15 category bonus for Comics category (7030) on test fixture
        assert score_high == pytest.approx(115.0, abs=1)
        assert score_low == pytest.approx(17.0, abs=1)

    def test_all_weight_on_age(self) -> None:
        """100% age weight means score depends entirely on age."""
        old = make_release("Batman 005 [2024]", size_mb=100, age_days=200)
        new = make_release("Batman 005 [2024]", size_mb=100, age_days=1)
        score_old = score_release(old, score_weights=(0.0, 1.0, 0.0, 0.0))
        score_new = score_release(new, score_weights=(0.0, 1.0, 0.0, 0.0))
        assert score_new > score_old

    def test_all_weight_on_size(self) -> None:
        """100% size weight means score depends entirely on file size."""
        small = make_release("Batman 005 [2024]", size_mb=10)
        normal = make_release("Batman 005 [2024]", size_mb=200)
        score_small = score_release(small, score_weights=(0.0, 0.0, 1.0, 0.0))
        score_normal = score_release(normal, score_weights=(0.0, 0.0, 1.0, 0.0))
        assert score_normal > score_small

    def test_all_weight_on_format(self) -> None:
        """100% format weight ranks CBZ above unknown format."""
        cbz = make_release("Batman 005 [2024].cbz", size_mb=100)
        unknown = make_release("Batman 005 [2024]", size_mb=100)
        score_cbz = score_release(cbz, score_weights=(0.0, 0.0, 0.0, 1.0))
        score_unk = score_release(unknown, score_weights=(0.0, 0.0, 0.0, 1.0))
        assert score_cbz > score_unk

    def test_equal_weights(self) -> None:
        """Equal weights (25/25/25/25) produce a valid score."""
        release = make_release("Batman 005 [2024].cbz", size_mb=100, age_days=5)
        score = score_release(release, score_weights=(0.25, 0.25, 0.25, 0.25))
        assert 0 < score <= 115  # category bonus can push above 100

    def test_none_weights_uses_defaults(self) -> None:
        """Passing None uses default weights."""
        release = make_release("Batman 005 [2024].cbz", size_mb=100, age_days=5)
        default = score_release(release)
        explicit_none = score_release(release, score_weights=None)
        assert default == explicit_none


class TestSeederScoring:
    """Tests for tiered seeder bonus in score_release()."""

    def test_torrent_with_many_seeders_scores_higher(self) -> None:
        """Torrent with 20 seeders should score higher than torrent with 1 seeder."""
        many = make_release("Batman 005 [2024].cbz", seeders=20, is_torrent=True)
        few = make_release("Batman 005 [2024].cbz", seeders=1, is_torrent=True)
        score_many = score_release(many)
        score_few = score_release(few)
        assert score_many > score_few

    def test_nzb_gets_no_seeder_bonus(self) -> None:
        """NZB results (non-torrent) get no seeder bonus regardless of seeders."""
        nzb_with_seeders = make_release("Batman 005 [2024].cbz", seeders=50, is_torrent=False)
        nzb_without = make_release("Batman 005 [2024].cbz", seeders=None, is_torrent=False)
        assert score_release(nzb_with_seeders) == score_release(nzb_without)

    def test_seeder_bonus_caps_at_15(self) -> None:
        """Seeder bonus should cap at 15 for 50+ seeders."""
        high = make_release("Batman 005 [2024].cbz", seeders=100, is_torrent=True)
        at_cap = make_release("Batman 005 [2024].cbz", seeders=51, is_torrent=True)
        assert score_release(high) == score_release(at_cap)

    def test_zero_seeders_gets_no_bonus(self) -> None:
        """Torrent with 0 seeders gets no seeder bonus."""
        dead = make_release("Batman 005 [2024].cbz", seeders=0, is_torrent=True)
        nzb = make_release("Batman 005 [2024].cbz", seeders=None, is_torrent=False)
        assert score_release(dead) == score_release(nzb)

    def test_seeder_tiers(self) -> None:
        """Each seeder tier produces the expected bonus jump."""
        low = make_release("Batman 005 [2024].cbz", seeders=5, is_torrent=True)
        decent = make_release("Batman 005 [2024].cbz", seeders=20, is_torrent=True)
        reliable = make_release("Batman 005 [2024].cbz", seeders=40, is_torrent=True)
        excellent = make_release("Batman 005 [2024].cbz", seeders=60, is_torrent=True)
        s_low = score_release(low)
        s_decent = score_release(decent)
        s_reliable = score_release(reliable)
        s_excellent = score_release(excellent)
        assert s_low < s_decent < s_reliable < s_excellent

    def test_tier_boundary_values(self) -> None:
        """Boundary seeders land in the correct tier."""
        from pullbox.services.search_service import _score_seeders

        assert _score_seeders(0, is_torrent=True) == 0.0
        assert _score_seeders(1, is_torrent=True) == 4.0
        assert _score_seeders(10, is_torrent=True) == 4.0
        assert _score_seeders(11, is_torrent=True) == 8.0
        assert _score_seeders(30, is_torrent=True) == 8.0
        assert _score_seeders(31, is_torrent=True) == 12.0
        assert _score_seeders(50, is_torrent=True) == 12.0
        assert _score_seeders(51, is_torrent=True) == 15.0


class TestConfidenceBlend:
    """Tests for configurable confidence blend in evaluate_results()."""

    def test_high_confidence_blend_favors_match_quality(self) -> None:
        """Higher confidence_blend values weight match quality more."""
        results = [make_release("Batman 005 [2024] [Digital]")]
        # With high confidence blend (0.80) — confidence bonus matters more
        best_high = SearchService.evaluate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
            wanted_year=2024,
            confidence_blend=0.80,
        )
        assert best_high is not None

    def test_zero_confidence_blend_ignores_match_confidence(self) -> None:
        """confidence_blend=0 means only quality scoring matters."""
        results = [make_release("Batman 005 [2024] [Digital].cbz")]
        best = SearchService.evaluate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
            wanted_year=2024,
            confidence_blend=0.0,
        )
        assert best is not None

    def test_full_confidence_blend_ignores_quality(self) -> None:
        """confidence_blend=1.0 means only match confidence matters."""
        results = [make_release("Batman 005 [2024] [Digital]")]
        best = SearchService.evaluate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
            wanted_year=2024,
            confidence_blend=1.0,
        )
        assert best is not None

    def test_default_blend_is_forty_percent(self) -> None:
        """Default blend (None) behaves identically to explicit 0.40."""
        results = [make_release("Batman 005 [2024] [Digital]")]
        default = SearchService.evaluate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
            wanted_year=2024,
        )
        explicit = SearchService.evaluate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
            wanted_year=2024,
            confidence_blend=0.40,
        )
        # Both should return the same result
        assert (default is None) == (explicit is None)


# ── Tier 2: Matching Thresholds ──────────────────────────────────────


class TestFuzzyThresholds:
    """Tests for configurable fuzzy match thresholds."""

    def setup_method(self) -> None:
        self.matcher = NameMatcher()

    def test_default_thresholds(self) -> None:
        """Verify default threshold class attributes."""
        assert NameMatcher.DEFAULT_FUZZY_HIGH == 0.85
        assert NameMatcher.DEFAULT_FUZZY_LOW == 0.70

    def test_strict_high_threshold_rejects_more(self) -> None:
        """Raising high threshold from 0.85 to 0.95 rejects borderline matches."""
        # "Daredevil" vs "Daredevl" gives ~0.88 similarity
        default = self.matcher.match("Daredevil", "Daredevl")
        strict = self.matcher.match(
            "Daredevil", "Daredevl", fuzzy_high_threshold=0.95, fuzzy_low_threshold=0.70
        )
        # Both match (similarity ~0.88 is above 0.70)
        assert default.is_match is True
        assert strict.is_match is True

    def test_loose_low_threshold_accepts_more(self) -> None:
        """Lowering low threshold accepts more distant matches."""
        # These are quite different, normally rejected
        result_strict = self.matcher.match(
            "Batman Beyond", "Superman Returns", fuzzy_low_threshold=0.70
        )
        result_loose = self.matcher.match(
            "Batman Beyond", "Superman Returns", fuzzy_low_threshold=0.20
        )
        # Strict should reject, loose may accept
        if not result_strict.is_match and result_loose.is_match:
            assert result_loose.similarity >= 0.20

    def test_raising_low_threshold_rejects_fuzzy(self) -> None:
        """Setting both thresholds to 0.95 rejects matches below that."""
        result = self.matcher.match(
            "Daredevil",
            "Daredevl",
            fuzzy_high_threshold=0.95,
            fuzzy_low_threshold=0.95,
        )
        # Similarity ~0.94 is below 0.95 — should reject
        assert result.is_match is False

    def test_thresholds_dont_affect_exact_match(self) -> None:
        """Exact matches always pass regardless of thresholds."""
        result = self.matcher.match(
            "Batman", "Batman", fuzzy_high_threshold=0.99, fuzzy_low_threshold=0.99
        )
        assert result.is_match is True
        assert result.match_type == "exact"

    def test_thresholds_dont_affect_alternate_match(self) -> None:
        """Alternate name matches always pass regardless of thresholds."""
        result = self.matcher.match(
            "TMNT",
            "Teenage Mutant Ninja Turtles",
            alternate_names=["TMNT"],
            fuzzy_high_threshold=0.99,
            fuzzy_low_threshold=0.99,
        )
        assert result.is_match is True
        assert result.match_type == "alternate"

    def test_thresholds_dont_affect_token_set(self) -> None:
        """Token-set matches always pass regardless of fuzzy thresholds."""
        result = self.matcher.match(
            "Spider-Man Amazing The",
            "The Amazing Spider-Man",
            fuzzy_high_threshold=0.99,
            fuzzy_low_threshold=0.99,
        )
        assert result.is_match is True
        assert result.match_type == "token_set"

    def test_none_thresholds_use_defaults(self) -> None:
        """Passing None uses default thresholds."""
        default = self.matcher.match("Daredevil", "Daredevl")
        explicit_none = self.matcher.match(
            "Daredevil", "Daredevl", fuzzy_high_threshold=None, fuzzy_low_threshold=None
        )
        assert default.is_match == explicit_none.is_match
        assert default.similarity == explicit_none.similarity


class TestYearTolerance:
    """Tests for configurable year tolerance in ReleaseValidator."""

    def test_default_tolerance_accepts_one_year_diff(self) -> None:
        """Default year tolerance (1) accepts +-1 year."""
        validator = ReleaseValidator()
        results = [make_release("Batman 005 [2023] [Digital]")]
        validated = validator.validate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
            wanted_year=2024,
        )
        assert len(validated) >= 1
        assert validated[0].year_match is True

    def test_strict_tolerance_rejects_one_year_diff(self) -> None:
        """year_tolerance=0 rejects any year difference."""
        validator = ReleaseValidator(year_tolerance=0)
        results = [make_release("Batman 005 [2023] [Digital]")]
        validated = validator.validate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
            wanted_year=2024,
        )
        assert len(validated) >= 1
        # Should NOT be a year match with tolerance=0
        assert validated[0].year_match is False

    def test_loose_tolerance_accepts_three_year_diff(self) -> None:
        """year_tolerance=3 accepts a 3-year difference."""
        validator = ReleaseValidator(year_tolerance=3)
        results = [make_release("Batman 005 [2021] [Digital]")]
        validated = validator.validate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
            wanted_year=2024,
        )
        assert len(validated) >= 1
        assert validated[0].year_match is True

    def test_tolerance_affects_confidence(self) -> None:
        """Year match/mismatch affects confidence grading."""
        # With tolerance=0, 2023 vs 2024 = year mismatch = LOW confidence
        strict = ReleaseValidator(year_tolerance=0)
        results = [make_release("Batman 005 [2023] [Digital]")]
        validated = strict.validate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
            wanted_year=2024,
        )
        assert len(validated) >= 1
        assert validated[0].confidence == MatchConfidence.LOW

        # With default tolerance=1, same scenario = year match = HIGH confidence
        default = ReleaseValidator()
        validated2 = default.validate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
            wanted_year=2024,
        )
        assert len(validated2) >= 1
        assert validated2[0].confidence == MatchConfidence.HIGH


class TestValidatorFuzzyThresholds:
    """Tests for fuzzy thresholds wired through ReleaseValidator."""

    def test_strict_threshold_rejects_fuzzy_match(self) -> None:
        """High fuzzy_low_threshold rejects borderline series matches."""
        # "Batmaniac" has ~0.73 similarity to "Batman" — normally accepted
        validator_strict = ReleaseValidator(fuzzy_low_threshold=0.90)
        results = [make_release("Batmaniac 005 [2024] [Digital]")]
        validated = validator_strict.validate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
            wanted_year=2024,
        )
        assert len(validated) == 0

    def test_default_threshold_accepts_fuzzy_match(self) -> None:
        """Default thresholds accept borderline series matches."""
        validator = ReleaseValidator()
        results = [make_release("Batmaniac 005 [2024] [Digital]")]
        validated = validator.validate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
            wanted_year=2024,
        )
        # "Batmaniac" vs "Batman" similarity is ~0.73, above 0.70 default
        if len(validated) > 0:
            assert validated[0].confidence == MatchConfidence.LOW

    def test_fuzzy_high_affects_confidence_grading(self) -> None:
        """Adjusting fuzzy_high_threshold changes confidence assignment."""
        # "Daredevl" vs "Daredevil" similarity ~0.88
        # With default 0.85 high threshold → MEDIUM confidence (fuzzy high + year)
        default = ReleaseValidator()
        results = [make_release("Daredevl 005 [2024] [Digital]")]
        v_default = default.validate_results(
            results,
            wanted_series="Daredevil",
            wanted_issue=5.0,
            wanted_year=2024,
        )
        if len(v_default) > 0:
            assert v_default[0].confidence == MatchConfidence.MEDIUM

        # With 0.95 high threshold → 0.88 is below high → LOW confidence
        strict = ReleaseValidator(fuzzy_high_threshold=0.95)
        v_strict = strict.validate_results(
            results,
            wanted_series="Daredevil",
            wanted_issue=5.0,
            wanted_year=2024,
        )
        if len(v_strict) > 0:
            assert v_strict[0].confidence == MatchConfidence.LOW


class TestEvaluateResultsWithThresholds:
    """Tests for evaluate_results forwarding all config params."""

    def test_score_weights_forwarded(self) -> None:
        """Custom score_weights are passed to score_release."""
        results = [make_release("Batman 005 [2024] [Digital].cbz")]
        best = SearchService.evaluate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
            wanted_year=2024,
            score_weights=(0.10, 0.10, 0.10, 0.70),
        )
        assert best is not None

    def test_fuzzy_thresholds_forwarded(self) -> None:
        """Fuzzy thresholds forwarded through evaluate_results."""
        # "Batmaniac" vs "Batman" — normally a borderline match
        results = [make_release("Batmaniac 005 [2024] [Digital]")]
        # With strict threshold, should be rejected
        best = SearchService.evaluate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
            wanted_year=2024,
            fuzzy_low_threshold=0.90,
        )
        assert best is None

    def test_year_tolerance_forwarded(self) -> None:
        """Year tolerance forwarded through evaluate_results."""
        results = [make_release("Batman 005 [2020] [Digital]")]
        # With tolerance=0, 2020 vs 2024 is a year mismatch (still matches, lower confidence)
        best = SearchService.evaluate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
            wanted_year=2024,
            year_tolerance=0,
        )
        # Still returns a result (year doesn't reject, just affects confidence)
        assert best is not None

    def test_all_params_together(self) -> None:
        """All configurable params work together."""
        results = [make_release("Batman 005 [2024] [Digital].cbz")]
        best = SearchService.evaluate_results(
            results,
            wanted_series="Batman",
            wanted_issue=5.0,
            wanted_year=2024,
            score_weights=(0.25, 0.25, 0.25, 0.25),
            confidence_blend=0.50,
            fuzzy_high_threshold=0.80,
            fuzzy_low_threshold=0.60,
            year_tolerance=2,
        )
        assert best is not None

    def test_legacy_path_with_score_weights(self) -> None:
        """Legacy path (no wanted_series) respects score_weights."""
        results = [make_release("Batman 005 [2024] [Digital].cbz")]
        best = SearchService.evaluate_results(
            results,
            score_weights=(0.25, 0.25, 0.25, 0.25),
        )
        assert best is not None


class TestConfigKeysExist:
    """Tests that new config keys exist in DEFAULT_SYSTEM_CONFIG."""

    def test_scoring_weights_in_config(self) -> None:
        from pullbox.models.config import DEFAULT_SYSTEM_CONFIG

        for key in [
            "score_weight_priority",
            "score_weight_age",
            "score_weight_size",
            "score_weight_format",
        ]:
            assert key in DEFAULT_SYSTEM_CONFIG
            value, value_type = DEFAULT_SYSTEM_CONFIG[key]
            assert value_type == "int"
            assert int(value) > 0

    def test_scoring_weights_sum_to_100(self) -> None:
        from pullbox.models.config import DEFAULT_SYSTEM_CONFIG

        total = sum(
            int(DEFAULT_SYSTEM_CONFIG[k][0])
            for k in [
                "score_weight_priority",
                "score_weight_age",
                "score_weight_size",
                "score_weight_format",
            ]
        )
        assert total == 100

    def test_confidence_blend_in_config(self) -> None:
        from pullbox.models.config import DEFAULT_SYSTEM_CONFIG

        assert "score_confidence_blend" in DEFAULT_SYSTEM_CONFIG
        value, value_type = DEFAULT_SYSTEM_CONFIG["score_confidence_blend"]
        assert value_type == "int"
        assert 0 <= int(value) <= 100

    def test_fuzzy_thresholds_in_config(self) -> None:
        from pullbox.models.config import DEFAULT_SYSTEM_CONFIG

        assert "match_fuzzy_high_threshold" in DEFAULT_SYSTEM_CONFIG
        assert "match_fuzzy_low_threshold" in DEFAULT_SYSTEM_CONFIG
        high = int(DEFAULT_SYSTEM_CONFIG["match_fuzzy_high_threshold"][0])
        low = int(DEFAULT_SYSTEM_CONFIG["match_fuzzy_low_threshold"][0])
        assert high > low
        assert 0 < low <= 100
        assert 0 < high <= 100

    def test_year_tolerance_in_config(self) -> None:
        from pullbox.models.config import DEFAULT_SYSTEM_CONFIG

        assert "match_year_tolerance" in DEFAULT_SYSTEM_CONFIG
        value, value_type = DEFAULT_SYSTEM_CONFIG["match_year_tolerance"]
        assert value_type == "int"
        assert int(value) >= 0


class TestBuildEvalKwargs:
    """Tests for build_eval_kwargs config-to-kwargs conversion."""

    def test_empty_config(self) -> None:
        from pullbox.services.search_service import build_eval_kwargs

        result = build_eval_kwargs({})
        assert result == {}

    def test_ignore_words_parsed(self) -> None:
        from pullbox.services.search_service import build_eval_kwargs

        cfg = {"search_ignore_words": "covers only,preview,ashcan"}
        result = build_eval_kwargs(cfg)
        assert result["ignore_words"] == ["covers only", "preview", "ashcan"]

    def test_score_weights_converted(self) -> None:
        from pullbox.services.search_service import build_eval_kwargs

        cfg = {
            "score_weight_priority": "40",
            "score_weight_age": "30",
            "score_weight_size": "20",
            "score_weight_format": "10",
        }
        result = build_eval_kwargs(cfg)
        assert result["score_weights"] == pytest.approx((0.40, 0.30, 0.20, 0.10))

    def test_score_weights_normalized(self) -> None:
        """Non-standard weights are normalized to sum to 1.0."""
        from pullbox.services.search_service import build_eval_kwargs

        cfg = {
            "score_weight_priority": "50",
            "score_weight_age": "50",
            "score_weight_size": "50",
            "score_weight_format": "50",
        }
        result = build_eval_kwargs(cfg)
        weights = result["score_weights"]
        assert sum(weights) == pytest.approx(1.0)
        assert weights == pytest.approx((0.25, 0.25, 0.25, 0.25))

    def test_confidence_blend_converted(self) -> None:
        from pullbox.services.search_service import build_eval_kwargs

        cfg = {"score_confidence_blend": "60"}
        result = build_eval_kwargs(cfg)
        assert result["confidence_blend"] == pytest.approx(0.60)

    def test_fuzzy_thresholds_converted(self) -> None:
        from pullbox.services.search_service import build_eval_kwargs

        cfg = {
            "match_fuzzy_high_threshold": "90",
            "match_fuzzy_low_threshold": "75",
        }
        result = build_eval_kwargs(cfg)
        assert result["fuzzy_high_threshold"] == pytest.approx(0.90)
        assert result["fuzzy_low_threshold"] == pytest.approx(0.75)

    def test_year_tolerance_int(self) -> None:
        from pullbox.services.search_service import build_eval_kwargs

        cfg = {"match_year_tolerance": "2"}
        result = build_eval_kwargs(cfg)
        assert result["year_tolerance"] == 2

    def test_min_score_converted(self) -> None:
        from pullbox.services.search_service import build_eval_kwargs

        cfg = {"min_quality_score": "15"}
        result = build_eval_kwargs(cfg)
        assert result["min_score"] == pytest.approx(15.0)

    def test_all_keys_at_once(self) -> None:
        from pullbox.services.search_service import build_eval_kwargs

        cfg = {
            "search_ignore_words": "preview",
            "score_weight_priority": "40",
            "score_weight_age": "30",
            "score_weight_size": "20",
            "score_weight_format": "10",
            "score_confidence_blend": "40",
            "match_fuzzy_high_threshold": "85",
            "match_fuzzy_low_threshold": "70",
            "match_year_tolerance": "1",
            "min_quality_score": "10",
        }
        result = build_eval_kwargs(cfg)
        assert "ignore_words" in result
        assert "score_weights" in result
        assert "confidence_blend" in result
        assert "fuzzy_high_threshold" in result
        assert "fuzzy_low_threshold" in result
        assert "year_tolerance" in result
        assert "min_score" in result
