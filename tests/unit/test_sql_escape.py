"""Unit tests for core.db_utils — SQL LIKE wildcard escaping.

Tests cover percent, underscore, backslash escaping, normal text passthrough,
combined patterns, and empty strings.

Run:
    pytest tests/unit/test_sql_escape.py -v
    pytest tests/unit/test_sql_escape.py -v --cov=pullbox.core.db_utils --cov-report=term-missing
"""

from pullbox.core.db_utils import escape_like


class TestEscapeLike:
    """Tests for escape_like() helper."""

    def test_escapes_percent(self) -> None:
        assert escape_like("100%") == "100\\%"

    def test_escapes_underscore(self) -> None:
        assert escape_like("user_name") == "user\\_name"

    def test_escapes_backslash(self) -> None:
        assert escape_like("path\\to") == "path\\\\to"

    def test_normal_text_unchanged(self) -> None:
        assert escape_like("Batman") == "Batman"

    def test_combined_escaping(self) -> None:
        assert escape_like("%_\\") == "\\%\\_\\\\"

    def test_empty_string(self) -> None:
        assert escape_like("") == ""

    def test_multiple_percents(self) -> None:
        assert escape_like("%%") == "\\%\\%"

    def test_multiple_underscores(self) -> None:
        assert escape_like("__init__") == "\\_\\_init\\_\\_"

    def test_mixed_safe_and_wildcards(self) -> None:
        assert escape_like("Batman_Returns 100%") == "Batman\\_Returns 100\\%"
