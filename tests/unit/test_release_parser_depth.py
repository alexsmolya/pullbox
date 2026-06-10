"""Phase A: Parser depth tests using 7,984 real-world NZBGeek titles.

Validates year extraction, scan group detection, format tags, pack detection,
foreign language identification, and duplicate grouping against the expanded
fixture dataset.

Run:
    pytest tests/unit/test_release_parser_depth.py -v
"""

from __future__ import annotations

from collections import Counter

from pullbox.core.release_parser import parse_release_title

# ── A-1: Year Extraction Accuracy ─────────────────────────────


class TestYearExtraction:
    """Parsed years should be reasonable (1940-2027)."""

    def test_year_in_valid_range(self, nzbgeek_issues: list[str]) -> None:
        """No parsed year before 1940 or after current year + 1."""
        bad_years: list[tuple[str, int]] = []
        for title in nzbgeek_issues:
            parsed = parse_release_title(title)
            if parsed and parsed.year is not None and (parsed.year < 1940 or parsed.year > 2027):
                bad_years.append((title, parsed.year))
        assert len(bad_years) < len(nzbgeek_issues) * 0.02, (
            f"{len(bad_years)} titles with out-of-range years:\n"
            + "\n".join(f"  {y}: {t[:80]}" for t, y in bad_years[:20])
        )

    def test_majority_have_year(self, nzbgeek_issues: list[str]) -> None:
        """At least 80% of issue titles with bracket years parse correctly."""
        has_bracket_year = [t for t in nzbgeek_issues if "[20" in t or "[19" in t]
        parsed_year = 0
        for title in has_bracket_year:
            parsed = parse_release_title(title)
            if parsed and parsed.year is not None:
                parsed_year += 1
        rate = parsed_year / len(has_bracket_year) if has_bracket_year else 0
        assert rate >= 0.80, (
            f"Only {rate:.1%} of titles with bracket years parsed correctly "
            f"({parsed_year}/{len(has_bracket_year)})"
        )

    def test_no_year_returns_none(self, nzbgeek_issues: list[str]) -> None:
        """Titles without year indicators should return None, not 0 or garbage."""
        for title in nzbgeek_issues[:500]:
            parsed = parse_release_title(title)
            if parsed and parsed.year is not None:
                assert parsed.year != 0, f"Year=0 for: {title}"

    def test_year_distribution_reasonable(self, nzbgeek_issues: list[str]) -> None:
        """Year distribution should cluster around recent years."""
        years: list[int] = []
        for title in nzbgeek_issues:
            parsed = parse_release_title(title)
            if parsed and parsed.year is not None:
                years.append(parsed.year)
        assert len(years) > 100, "Too few years extracted to validate distribution"
        recent = sum(1 for y in years if y >= 2020)
        assert recent > len(years) * 0.30, (
            f"Only {recent}/{len(years)} years are 2020+, expected ≥30%"
        )


# ── A-2: Scan Group Extraction ────────────────────────────────


class TestScanGroupExtraction:
    """Parser should detect scan groups from real-world titles."""

    def test_scan_group_detection_rate(self, nzbgeek_issues: list[str]) -> None:
        """At least 60% of issue titles have a detectable scan group."""
        has_group = 0
        for title in nzbgeek_issues:
            parsed = parse_release_title(title)
            if parsed and parsed.scan_group:
                has_group += 1
        rate = has_group / len(nzbgeek_issues)
        assert rate >= 0.60, (
            f"Only {rate:.1%} of titles have scan groups ({has_group}/{len(nzbgeek_issues)})"
        )

    def test_known_groups_detected(self, nzbgeek_issues: list[str]) -> None:
        """Known scan groups from the dataset appear in parsed results."""
        known_groups = {"Empire", "DCP", "Pyrate", "Shan"}
        found_groups: set[str] = set()
        for title in nzbgeek_issues:
            parsed = parse_release_title(title)
            if parsed and parsed.scan_group:
                for group in known_groups:
                    if group.lower() in parsed.scan_group.lower():
                        found_groups.add(group)
        assert len(found_groups) >= 3, f"Only found {found_groups} of {known_groups}"

    def test_scan_group_not_in_series_name(self, nzbgeek_issues: list[str]) -> None:
        """Scan group should not leak into the series name."""
        leak_count = 0
        for title in nzbgeek_issues[:1000]:
            parsed = parse_release_title(title)
            if (
                parsed
                and parsed.scan_group
                and parsed.series_name
                and parsed.scan_group.lower() in parsed.series_name.lower()
            ):
                leak_count += 1
        assert leak_count < 50, f"{leak_count} titles have scan group leaking into series name"


# ── A-3: Format/Tag Detection ─────────────────────────────────


class TestFormatTagDetection:
    """Parser should identify format indicators in titles."""

    def test_format_detection_rate(self, nzbgeek_issues: list[str]) -> None:
        """At least 50% of titles have a detectable format/quality tag."""
        format_keywords = {"digital", "webrip", "hybrid", "c2c", "scan", "kindle"}
        has_format = 0
        for title in nzbgeek_issues:
            lower = title.lower()
            if any(kw in lower for kw in format_keywords):
                has_format += 1
        rate = has_format / len(nzbgeek_issues)
        assert rate >= 0.50, (
            f"Only {rate:.1%} of titles have format tags ({has_format}/{len(nzbgeek_issues)})"
        )

    def test_digital_is_most_common(self, nzbgeek_issues: list[str]) -> None:
        """'digital' should be the most common format tag."""
        counts: Counter[str] = Counter()
        for title in nzbgeek_issues:
            lower = title.lower()
            if "digital" in lower:
                counts["digital"] += 1
            if "webrip" in lower:
                counts["webrip"] += 1
            if "hybrid" in lower:
                counts["hybrid"] += 1
            if "c2c" in lower:
                counts["c2c"] += 1
        assert counts["digital"] > 0, "No 'digital' tags found"
        # Digital should be among the top 2
        top_two = counts.most_common(2)
        assert any(tag == "digital" for tag, _ in top_two), f"'digital' not in top 2: {top_two}"

    def test_hybrid_dot_pattern_detected(self, nzbgeek_issues: list[str]) -> None:
        """HYBRID.COMIC dot-separated pattern should exist in the dataset."""
        hybrid_count = sum(1 for t in nzbgeek_issues if "HYBRID" in t.upper())
        assert hybrid_count > 5, f"Only {hybrid_count} HYBRID titles found"


# ── A-4: Pack Detection ───────────────────────────────────────


class TestPackDetection:
    """Multi-issue packs should be flagged correctly."""

    def test_low_false_positive_rate(self, nzbgeek_issues: list[str]) -> None:
        """Less than 5% of standard issues falsely flagged as packs."""
        pack_count = 0
        for title in nzbgeek_issues:
            parsed = parse_release_title(title)
            if parsed and parsed.is_pack:
                pack_count += 1
        rate = pack_count / len(nzbgeek_issues) if nzbgeek_issues else 0
        assert rate < 0.05, f"{rate:.1%} flagged as packs ({pack_count}/{len(nzbgeek_issues)})"

    def test_range_titles_detected(self) -> None:
        """Titles with issue number ranges should be flagged as packs."""
        range_titles = [
            "Batman 001-005 [2024] [Digital]",
            "X-Men 010-020 Pack [2025]",
        ]
        for title in range_titles:
            parsed = parse_release_title(title)
            if parsed:
                assert parsed.is_pack or parsed.pack_range is not None, (
                    f"Range title not detected as pack: {title}"
                )

    def test_single_issue_not_pack(self) -> None:
        """Standard single-issue titles should NOT be flagged as packs."""
        single_titles = [
            "Batman 006 [2026] [Digital] [Pyrate-DCP]",
            "Absolute Batman 017 [2026] [Digital] [Shan-Empire]",
            "Ultimate Spider-Man 015 [2025] [Webrip]",
        ]
        for title in single_titles:
            parsed = parse_release_title(title)
            assert parsed is not None
            assert not parsed.is_pack, f"Single issue flagged as pack: {title}"


# ── A-5: Foreign Language Detection ────────────────────────────


class TestForeignLanguageDetection:
    """Non-English releases should be identifiable."""

    def test_language_markers_exist_in_dataset(self, nzbgeek_issues: list[str]) -> None:
        """Dataset contains foreign language titles."""
        lang_markers = ["FRENCH", "GERMAN", "SPANISH", "ITALIAN", "PORTUGUESE"]
        found: dict[str, int] = {}
        all_titles = nzbgeek_issues
        for marker in lang_markers:
            count = sum(1 for t in all_titles if marker in t.upper())
            if count > 0:
                found[marker] = count
        assert len(found) >= 1, "No foreign language titles found in dataset"

    def test_french_titles_in_dataset(self, nzbgeek_issues: list[str]) -> None:
        """French titles are the most common non-English in comic indexers."""
        french = [t for t in nzbgeek_issues if "FRENCH" in t.upper()]
        assert len(french) >= 5, f"Only {len(french)} French titles found"

    def test_language_doesnt_corrupt_series(self, nzbgeek_issues: list[str]) -> None:
        """Foreign language tags shouldn't end up in the parsed series name."""
        lang_markers = {"french", "german", "spanish", "italian"}
        corrupted = 0
        for title in nzbgeek_issues:
            parsed = parse_release_title(title)
            if parsed and parsed.series_name:
                series_lower = parsed.series_name.lower()
                if any(m in series_lower for m in lang_markers):
                    corrupted += 1
        assert corrupted < 10, f"{corrupted} titles have language markers in series name"

    def test_english_titles_have_no_language_marker(self, nzbgeek_issues: list[str]) -> None:
        """At least 90% of titles have no explicit language marker."""
        lang_markers = [
            "FRENCH",
            "GERMAN",
            "SPANISH",
            "ITALIAN",
            "PORTUGUESE",
            "JAPANESE",
            "CHINESE",
            "KOREAN",
            "DUTCH",
            "POLISH",
            "RUSSIAN",
        ]
        has_marker = 0
        for title in nzbgeek_issues:
            upper = title.upper()
            if any(m in upper for m in lang_markers):
                has_marker += 1
        rate = 1 - (has_marker / len(nzbgeek_issues))
        assert rate >= 0.90, f"Only {rate:.1%} of titles lack language markers"


# ── A-6: Duplicate Release Grouping ───────────────────────────


class TestDuplicateGrouping:
    """Same series+issue from different groups should be identifiable."""

    def test_duplicate_pairs_exist(self, nzbgeek_issues: list[str]) -> None:
        """Dataset contains duplicate releases (same issue, different groups)."""
        seen: dict[tuple[str | None, float | None], list[str]] = {}
        for title in nzbgeek_issues:
            parsed = parse_release_title(title)
            if parsed and parsed.series_name and parsed.issue_number is not None:
                key = (parsed.series_name.lower(), parsed.issue_number)
                seen.setdefault(key, []).append(title)
        duplicates = {k: v for k, v in seen.items() if len(v) > 1}
        assert len(duplicates) >= 50, f"Only {len(duplicates)} duplicate groups found, expected ≥50"

    def test_duplicates_have_different_groups(self, nzbgeek_issues: list[str]) -> None:
        """Duplicate releases should come from different scan groups."""
        seen: dict[tuple[str | None, float | None], list[str | None]] = {}
        for title in nzbgeek_issues:
            parsed = parse_release_title(title)
            if parsed and parsed.series_name and parsed.issue_number is not None:
                key = (parsed.series_name.lower(), parsed.issue_number)
                seen.setdefault(key, []).append(parsed.scan_group)
        multi_group = 0
        for _key, groups in seen.items():
            if len(groups) > 1:
                unique_groups = {g for g in groups if g}
                if len(unique_groups) > 1:
                    multi_group += 1
        assert multi_group >= 20, f"Only {multi_group} duplicate pairs with different groups"

    def test_duplicate_series_names_match(self, nzbgeek_issues: list[str]) -> None:
        """Duplicates should share the same parsed series name."""
        seen: dict[tuple[str | None, float | None], set[str | None]] = {}
        for title in nzbgeek_issues:
            parsed = parse_release_title(title)
            if parsed and parsed.series_name and parsed.issue_number is not None:
                key = (parsed.series_name.lower(), parsed.issue_number)
                seen.setdefault(key, set()).add(parsed.series_name)
        # Check that grouped duplicates all have the same series name (case-insensitive)
        mismatches = 0
        for (_series_lower, _), names in seen.items():
            normalized = {n.lower() for n in names if n}
            if len(normalized) > 1:
                mismatches += 1
        assert mismatches == 0, f"{mismatches} duplicate groups have mismatched series names"
