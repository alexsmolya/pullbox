"""Cross-modality tests: same parser + matcher for both disk files and NZB titles.

Verifies that NameMatcher and parse_release_title produce consistent results
regardless of whether the input is a local filename or an NZB release title.

Run:
    pytest tests/integration/test_cross_modality.py -v
"""

import pytest

from pullbox.core.name_matcher import NameMatcher
from pullbox.core.release_parser import parse_release_title
from pullbox.models.issue import IssueType


@pytest.mark.cross_modality
class TestCrossModality:
    """Same parser works on both local filenames and NZB titles."""

    def test_same_series_from_nzb_and_file(self) -> None:
        """NZB title and local filename parse to same normalized series name."""
        nzb = parse_release_title("Batman 005 [2024] [Digital] [Shan-Empire]")
        local = parse_release_title("Batman (2024) #005 (Digital) (Zone-Empire).cbz")

        assert nzb is not None
        assert local is not None

        matcher = NameMatcher()
        assert matcher.normalize(nzb.series_name or "") == matcher.normalize(
            local.series_name or ""
        )

    def test_same_issue_from_nzb_and_file(self) -> None:
        """NZB title and local filename parse to same issue number."""
        nzb = parse_release_title("Amazing Spider-Man 022 [2024] [Digital]")
        local = parse_release_title("Amazing Spider-Man #022 (2024).cbz")

        assert nzb is not None
        assert local is not None
        assert nzb.issue_number == local.issue_number == 22.0

    def test_annual_detected_in_both(self) -> None:
        """Annual type detected in both NZB and local filenames."""
        nzb = parse_release_title("Batman Annual 003 [2024] [Digital]")
        local = parse_release_title("Batman Annual #003 (2024).cbz")

        assert nzb is not None
        assert local is not None
        assert nzb.issue_type == IssueType.ANNUAL
        assert local.issue_type == IssueType.ANNUAL

    def test_name_matcher_normalizes_both_equally(self) -> None:
        """NameMatcher.normalize() produces identical results for both modalities."""
        matcher = NameMatcher()

        # NZB titles often have HTML entities
        nzb_series = "Batman &amp; Superman"
        # Local filenames use literal characters
        local_series = "Batman & Superman"

        assert matcher.normalize(nzb_series) == matcher.normalize(local_series)

    def test_year_extracted_from_both_formats(self) -> None:
        """Year is extracted from bracket [2024] and paren (2024) formats."""
        nzb = parse_release_title("X-Men 025 [2024] [Digital]")
        local = parse_release_title("X-Men (2024) #025.cbz")

        assert nzb is not None
        assert local is not None
        assert nzb.year == local.year == 2024
