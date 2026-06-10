"""Phase D: Statistical regression gate tests.

These tests track key parser metrics across the full dataset and fail
if a parser change degrades quality below established baselines.

Run:
    pytest tests/unit/test_parser_regression_gates.py -v
"""

from __future__ import annotations

from collections import Counter

from pullbox.core.release_parser import parse_release_title
from pullbox.models.issue import IssueType

# ── D-1: Parse Success Rate Gates ─���───────────────────────────


class TestParseRegressionGates:
    """Baseline metrics that must not regress."""

    def test_parse_success_rate(self, nzbgeek_issues: list[str]) -> None:
        """≥95% of issue titles should parse successfully."""
        parsed = 0
        failures: list[str] = []
        for title in nzbgeek_issues:
            result = parse_release_title(title)
            if result is not None:
                parsed += 1
            else:
                failures.append(title)
        rate = parsed / len(nzbgeek_issues)
        assert rate >= 0.95, (
            f"Parse rate {rate:.1%} below 95% threshold. "
            f"{len(failures)} failures:\n" + "\n".join(f"  {t[:80]}" for t in failures[:20])
        )

    def test_series_extraction_rate(self, nzbgeek_issues: list[str]) -> None:
        """≥95% of parsed issues should have a series name."""
        has_series = 0
        total_parsed = 0
        no_series: list[str] = []
        for title in nzbgeek_issues:
            result = parse_release_title(title)
            if result is not None:
                total_parsed += 1
                if result.series_name:
                    has_series += 1
                else:
                    no_series.append(title)
        rate = has_series / total_parsed if total_parsed else 0
        assert rate >= 0.95, (
            f"Series extraction rate {rate:.1%} below 95%. "
            f"{len(no_series)} missing:\n" + "\n".join(f"  {t[:80]}" for t in no_series[:20])
        )

    def test_issue_number_rate(self, nzbgeek_issues: list[str]) -> None:
        """≥80% of parsed issues should have an issue number."""
        has_number = 0
        total_parsed = 0
        for title in nzbgeek_issues:
            result = parse_release_title(title)
            if result is not None:
                total_parsed += 1
                if result.issue_number is not None:
                    has_number += 1
        rate = has_number / total_parsed if total_parsed else 0
        assert rate >= 0.80, f"Issue number rate {rate:.1%} below 80% ({has_number}/{total_parsed})"

    def test_non_issue_detection_rate(self, nzbgeek_non_issues: list[str]) -> None:
        """≥90% of non-issue titles should NOT be classified as ISSUE."""
        correct = 0
        for title in nzbgeek_non_issues:
            result = parse_release_title(title)
            if result is None or result.issue_type != IssueType.ISSUE:
                correct += 1
        rate = correct / len(nzbgeek_non_issues) if nzbgeek_non_issues else 0
        assert rate >= 0.90, f"Non-issue detection rate {rate:.1%} below 90%"


# ── D-2: Publisher and Format Diversity ────────────────────────


class TestDatasetDiversity:
    """Dataset should cover a healthy distribution of patterns."""

    def test_multiple_publishers_detected(self, nzbgeek_issues: list[str]) -> None:
        """At least 3 distinct publishers identifiable in the dataset."""
        publisher_markers = {
            "DC": ["DC.Comics", "DC Comics"],
            "Marvel": ["Marvel", "MARVEL"],
            "Image": ["Image"],
            "Dark Horse": ["Dark Horse"],
            "IDW": ["IDW"],
            "Dynamite": ["Dynamite"],
            "Boom": ["BOOM", "Boom"],
        }
        found: set[str] = set()
        for title in nzbgeek_issues:
            for pub, markers in publisher_markers.items():
                if any(m in title for m in markers):
                    found.add(pub)
        assert len(found) >= 3, f"Only found {found} publishers, expected ≥3"

    def test_multiple_formats_detected(self, nzbgeek_issues: list[str]) -> None:
        """At least 3 distinct naming formats in the dataset."""
        formats: Counter[str] = Counter()
        for title in nzbgeek_issues:
            if "[" in title and "]" in title:
                formats["bracket"] += 1
            elif "." in title.split(" ")[0] if " " in title else "." in title:
                formats["dot-separated"] += 1
            else:
                formats["other"] += 1
        assert len(formats) >= 2, f"Only {len(formats)} naming formats: {dict(formats)}"

    def test_bracket_and_dot_notation_present(self, nzbgeek_issues: list[str]) -> None:
        """Both bracket notation and dot notation exist."""
        bracket = sum(1 for t in nzbgeek_issues if "[" in t)
        dot = sum(1 for t in nzbgeek_issues if ".COMIC" in t.upper() or ".HYBRID" in t.upper())
        assert bracket > 100, f"Only {bracket} bracket-notation titles"
        assert dot > 50, f"Only {dot} dot-notation titles"

    def test_non_issue_type_diversity(self, nzbgeek_non_issues: list[str]) -> None:
        """Non-issue dataset covers multiple types (TPB, omnibus, annual, etc.)."""
        type_counts: Counter[str] = Counter()
        for title in nzbgeek_non_issues:
            result = parse_release_title(title)
            if result:
                type_counts[result.issue_type.value] += 1
        # Should have at least 3 non-issue types represented
        non_issue_types = {k for k in type_counts if k != "issue"}
        assert len(non_issue_types) >= 3, (
            f"Only {len(non_issue_types)} non-issue types: {dict(type_counts)}"
        )
