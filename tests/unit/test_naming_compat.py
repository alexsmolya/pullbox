"""Backward compatibility tests for parse_filename() after delegation.

Verifies that the naming.py parse_filename() wrapper still produces
identical results after switching to parse_release_title() internally.

Run:
    pytest tests/unit/test_naming_compat.py -v
"""

import pytest

from pullbox.core.naming import parse_filename


class TestNamingBackwardCompatibility:
    """Verify parse_filename() still works after delegation.

    All 80 tests in test_naming.py must ALSO pass unchanged.
    """

    @pytest.mark.parametrize(
        ("filename", "expected_series", "expected_issue"),
        [
            ("Batman (2016) #045 (Digital) (Zone-Empire).cbz", "Batman", 45.0),
            ("Batman 045 (2016) (Digital-Empire).cbz", "Batman", 45.0),
            ("Batman #045 (2016).cbz", "Batman", 45.0),
            ("Batman 045.cbz", "Batman", 45.0),
            ("Batman #45.cbz", "Batman", 45.0),
        ],
    )
    def test_legacy_filenames_parse(
        self, filename: str, expected_series: str, expected_issue: float
    ) -> None:
        result = parse_filename(filename)
        assert result is not None
        assert result.series == expected_series
        assert result.issue_number == expected_issue

    def test_parsed_filename_has_issue_type(self) -> None:
        result = parse_filename("Batman Annual 003 (2018).cbz")
        assert result is not None
        assert hasattr(result, "issue_type")
        assert result.issue_type == "annual"

    def test_parsed_filename_has_volume(self) -> None:
        result = parse_filename("Amazing Spider-Man v2 015 (2000).cbz")
        assert result is not None
        assert hasattr(result, "volume")

    def test_format_filename_unchanged(self) -> None:
        from pullbox.core.naming import format_filename

        result = format_filename("Batman", 1, 2016)
        assert result == "Batman (2016) #001.cbz"

    def test_detect_issue_type_unchanged(self) -> None:
        from pullbox.core.naming import detect_issue_type

        assert detect_issue_type("Batman Annual 001") == "annual"
        assert detect_issue_type("Batman 045") == "issue"

    def test_no_match_returns_none(self) -> None:
        """Inputs without issue numbers still return None."""
        assert parse_filename("just-some-random-text") is None

    def test_extension_preserved(self) -> None:
        result = parse_filename("Batman 045 (2016).cbr")
        assert result is not None
        assert result.extension == "cbr"

    def test_year_extracted(self) -> None:
        result = parse_filename("Batman (2024) #005.cbz")
        assert result is not None
        assert result.year == 2024

    def test_tags_still_extracted(self) -> None:
        result = parse_filename("Batman Annual 001 (2026) (Digital).cbz")
        assert result is not None
        assert "Annual" in result.tags
        assert "Digital" in result.tags

    def test_default_issue_type_is_issue(self) -> None:
        result = parse_filename("Batman 045 (2016).cbz")
        assert result is not None
        assert result.issue_type == "issue"
