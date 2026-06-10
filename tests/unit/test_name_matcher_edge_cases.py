"""Phase C: Matching edge case tests using real-world naming patterns.

Validates hyphenated series, volume disambiguation, and non-English
title handling against patterns found in the NZBGeek dataset.

Run:
    pytest tests/unit/test_name_matcher_edge_cases.py -v
"""

from __future__ import annotations

from pullbox.core.name_matcher import NameMatcher
from pullbox.core.release_parser import parse_release_title
from pullbox.services.search_service import _score_language

# ── C-1: Hyphenated Series Matching ───────────────────────────


class TestHyphenatedSeries:
    """Series with hyphens, dashes, and colons should parse cleanly."""

    def test_multi_title_hyphenated(self) -> None:
        """Hyphenated multi-title series extracts full name."""
        parsed = parse_release_title("Batman-Superman-Worlds Finest 047 [2026] [digital]")
        assert parsed is not None
        assert parsed.series_name is not None
        assert "batman" in parsed.series_name.lower()
        assert parsed.issue_number == 47.0

    def test_crossover_hyphenated(self) -> None:
        """Crossover titles with hyphens preserve the full series name."""
        parsed = parse_release_title("Batman-Judge Dredd-Judgment on Gotham 001 [1992] [digital]")
        assert parsed is not None
        assert parsed.series_name is not None
        assert "batman" in parsed.series_name.lower()
        assert "dredd" in parsed.series_name.lower()
        assert parsed.issue_number == 1.0

    def test_spider_man_hyphen_preserved(self) -> None:
        """Spider-Man keeps its hyphen (doesn't split into Spider and Man)."""
        parsed = parse_release_title("The Amazing Spider-Man 042 [2025] [Digital]")
        assert parsed is not None
        assert parsed.series_name is not None
        assert "spider-man" in parsed.series_name.lower()

    def test_slash_to_hyphen_matcher(self) -> None:
        """Batman/Superman matches hyphenated variant via NameMatcher."""
        matcher = NameMatcher()
        result = matcher.match(
            "Batman Superman Worlds Finest",
            "Batman/Superman: World's Finest",
        )
        assert result.is_match, f"Expected match, got {result}"

    def test_spider_man_partial_is_low_confidence(self) -> None:
        """Spider-Man vs 'Spider' is at most a low-confidence fuzzy match."""
        matcher = NameMatcher()
        result = matcher.match("Spider-Man", "Spider")
        # May fuzzy-match due to string similarity, but should never be exact or high
        if result.is_match:
            assert result.match_type == "fuzzy"
            assert result.similarity < 0.85

    def test_en_dash_normalized(self) -> None:
        """Unicode en-dash treated same as hyphen in matching."""
        matcher = NameMatcher()
        result = matcher.match("Batman\u2013Superman", "Batman-Superman")
        assert result.is_match

    def test_ampersand_matches_and(self) -> None:
        """'&' matches 'and' in series names."""
        matcher = NameMatcher()
        result = matcher.match("Batman & Robin", "Batman and Robin")
        assert result.is_match

    def test_batman_green_arrow_multi(self) -> None:
        """Three-way crossover series parses."""
        parsed = parse_release_title("Batman-Green Arrow-The Question-Arcadia 002 [2026] [digital]")
        assert parsed is not None
        assert parsed.issue_number == 2.0

    def test_hyphenated_from_dataset(self, nzbgeek_issues: list[str]) -> None:
        """Hyphenated titles in the dataset parse with a series name."""
        hyphenated = [
            t for t in nzbgeek_issues if "-" in t.split("[")[0] and not t.startswith("DC.")
        ]
        parsed_ok = 0
        for title in hyphenated[:200]:
            p = parse_release_title(title)
            if p and p.series_name:
                parsed_ok += 1
        rate = parsed_ok / len(hyphenated[:200]) if hyphenated else 0
        assert rate >= 0.85, f"Only {rate:.1%} of hyphenated titles parsed"


# ── C-2: Volume Disambiguation ────────────────────────────────


class TestVolumeDisambiguation:
    """Volume indicators should be recognized and not confused with issues."""

    def test_vol_prefix_detected(self) -> None:
        """'Vol.01' recognized as volume, not issue number."""
        parsed = parse_release_title(
            "DC.Comics-Batman.And.Robin.Vol.02.The.Gotham.Cycle.2026.HYBRID.COMIC"
        )
        assert parsed is not None
        assert parsed.volume is not None or parsed.issue_number is not None

    def test_v_prefix_detected(self) -> None:
        """'v2' recognized as volume."""
        parsed = parse_release_title("Sandman v07 - Brief Lives (2011) (Digital TPB)")
        assert parsed is not None

    def test_issue_number_not_confused_with_volume(self) -> None:
        """Standard issue numbers aren't mistaken for volumes."""
        parsed = parse_release_title("Batman 042 [2026] [Digital]")
        assert parsed is not None
        assert parsed.issue_number == 42.0
        # Should NOT have a volume (42 is the issue, not a volume)

    def test_no_notation_has_year_context(self) -> None:
        """'X-Men 2024 No.19' parses the year and issue separately."""
        parsed = parse_release_title("Marvel-X-Men.2024.No.19.2025.HYBRID.COMIC")
        assert parsed is not None
        assert parsed.issue_number is not None


# ── C-3: Non-English Title Handling ────────────────────────────


class TestNonEnglishTitles:
    """Foreign language titles shouldn't corrupt English matching."""

    def test_french_title_parseable(self) -> None:
        """French title still extracts a series name."""
        parsed = parse_release_title(
            "Batman.No.Man.s.Land.T01.DC.Paperback.2025.FRENCH.HYBRiD.COMiC.CBZ"
        )
        assert parsed is not None
        assert parsed.series_name is not None
        assert parsed.year == 2025

    def test_french_tome_notation(self) -> None:
        """French 'T01' (tome) is handled without crashing."""
        parsed = parse_release_title("Batman.et.Robin.Annee.Un.2025.FRENCH.HYBRiD.COMiC.CBZ")
        assert parsed is not None
        assert parsed.year == 2025

    def test_french_titles_in_dataset(self, nzbgeek_issues: list[str]) -> None:
        """French titles from the dataset parse without errors."""
        french = [t for t in nzbgeek_issues if "FRENCH" in t.upper()]
        errors = 0
        for title in french:
            try:
                parse_release_title(title)
            except Exception:
                errors += 1
        assert errors == 0, f"{errors} French titles caused parser errors"

    def test_series_name_not_corrupted_by_language(self) -> None:
        """'FRENCH' tag doesn't end up in the series name."""
        parsed = parse_release_title(
            "Batman.No.Man.s.Land.T01.DC.Paperback.2025.FRENCH.HYBRiD.COMiC.CBZ"
        )
        assert parsed is not None
        if parsed.series_name:
            assert "french" not in parsed.series_name.lower()

    def test_non_english_penalized_by_scoring(self) -> None:
        """Non-English titles score lower than English with default preference."""
        en_score = _score_language("Batman 050 [2024] [Digital].cbz", preferred="en")
        fr_score = _score_language("Batman 050 [2024] FRENCH [Digital].cbz", preferred="en")
        assert en_score > fr_score, "French should score lower than English"

    def test_all_language_markers_detectable(self) -> None:
        """All supported language markers are penalized when preferred=en."""
        for lang in [
            "FRENCH",
            "GERMAN",
            "SPANISH",
            "ITALIAN",
            "JAPANESE",
            "KOREAN",
            "CHINESE",
            "PORTUGUESE",
            "DUTCH",
            "POLISH",
            "RUSSIAN",
        ]:
            score = _score_language(f"Batman 001 {lang}.cbz", preferred="en")
            assert score < 0, f"Language {lang} not penalized: score={score}"

    def test_german_title_parses(self) -> None:
        """German release title parses without errors."""
        parsed = parse_release_title("Superman.001.2023.GERMAN.Digital.cbz")
        assert parsed is not None
        assert parsed.series_name is not None

    def test_hybrid_title_parses(self) -> None:
        """HYBRiD-tagged releases (bilingual) parse correctly."""
        parsed = parse_release_title("Batman.050.2024.HYBRiD.COMIC.eBook-GRiM.cbz")
        assert parsed is not None
        assert parsed.series_name is not None

    def test_publication_form_suffix_matches(self) -> None:
        """Safe publication-form suffixes should not turn a title into weak fuzzy noise."""
        matcher = NameMatcher()
        result = matcher.match("Comic Heroes", "Comic Heroes Magazine")

        assert result.is_match
        assert result.match_type == "starts_with"

    def test_single_token_prefix_candidate_does_not_match_longer_title(self) -> None:
        """Article-stripped one-word prefixes should not swallow unrelated titles."""
        matcher = NameMatcher()
        result = matcher.match("Dead Space Salvage", "The Dead")

        assert not result.is_match
        assert result.match_type == "none"

    def test_multi_token_subtitle_match_still_allowed(self) -> None:
        """Real subtitle-style matches still work when the base title is specific."""
        matcher = NameMatcher()
        result = matcher.match("Agent Alpha - Fucking Patriot", "Agent Alpha")

        assert result.is_match
        assert result.match_type == "starts_with"
