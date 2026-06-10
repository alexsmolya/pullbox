"""NZBGeek fixture tests for the release parser (497 real-world titles).

Validates parser accuracy against actual NZB release titles captured from
NZBGeek search results.  These are acceptance tests — not unit tests for
individual functions.

Run:
    pytest tests/unit/test_release_parser_nzbgeek.py -v
    pytest tests/unit/test_release_parser_nzbgeek.py -k "issue" -v
"""

import pytest

from pullbox.core.release_parser import parse_release_title
from pullbox.models.issue import IssueType


@pytest.mark.nzbgeek
class TestReleaseParserRealWorld:
    """Test parser against real NZBGeek data (497 titles)."""

    def test_all_issue_titles_parse(self, nzbgeek_issues: list[str]) -> None:
        """>=95% of 234 issue titles should parse without errors."""
        failures: list[str] = []
        for title in nzbgeek_issues:
            parsed = parse_release_title(title)
            if parsed is None:
                failures.append(title)
        threshold = len(nzbgeek_issues) * 0.05
        assert len(failures) < threshold, (
            f"{len(failures)}/{len(nzbgeek_issues)} titles failed to parse "
            f"(>{threshold:.0f} threshold):\n" + "\n".join(f"  - {t}" for t in failures[:20])
        )

    def test_issue_titles_extract_series(self, nzbgeek_issues: list[str]) -> None:
        """>=95% of parsed issue titles should extract a series name."""
        no_series: list[str] = []
        for title in nzbgeek_issues:
            parsed = parse_release_title(title)
            if parsed and not parsed.series_name:
                no_series.append(title)
        assert len(no_series) < len(nzbgeek_issues) * 0.05

    def test_issue_titles_have_issue_number(self, nzbgeek_issues: list[str]) -> None:
        """>=80% of parsed issue titles should have an issue number.

        The fixture includes some volume-only titles (v01, Vol.02, T01)
        classified as "issues" by the NZBGeek categorization.  These correctly
        parse with volume but no issue_number.  Threshold is 80% to account
        for this.
        """
        no_issue: list[str] = []
        for title in nzbgeek_issues:
            parsed = parse_release_title(title)
            if parsed and parsed.issue_number is None:
                no_issue.append(title)
        assert len(no_issue) < len(nzbgeek_issues) * 0.20, (
            f"{len(no_issue)}/{len(nzbgeek_issues)} titles missing issue number "
            f"(>{len(nzbgeek_issues) * 0.20:.0f} threshold):\n"
            + "\n".join(f"  - {t}" for t in no_issue[:20])
        )

    def test_non_issue_titles_detect_type(self, nzbgeek_non_issues: list[str]) -> None:
        """<10% of non-issue titles misidentified as ISSUE.

        The non-issue fixture has been post-processed to remove regular
        issues that leaked in from series-name queries. The remaining
        titles are genuinely non-standard formats (TPB, omnibus, annual,
        one-shot, etc.), so the parser should correctly classify >90%.
        """
        detected_as_issue: list[str] = []
        for title in nzbgeek_non_issues:
            parsed = parse_release_title(title)
            if parsed and parsed.issue_type == IssueType.ISSUE:
                detected_as_issue.append(title)
        assert len(detected_as_issue) < len(nzbgeek_non_issues) * 0.10, (
            f"{len(detected_as_issue)} non-issue titles incorrectly detected as ISSUE"
        )
