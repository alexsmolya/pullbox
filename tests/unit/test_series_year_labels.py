"""Tests for status-aware series year range formatting."""

from __future__ import annotations

from pullbox.models.series import SeriesStatus
from pullbox.ui.routes import _format_series_year_label

_EN_DASH = "\u2013"


def test_continuing_series_without_end_year_shows_present() -> None:
    assert (
        _format_series_year_label(2016, None, SeriesStatus.CONTINUING) == f"2016{_EN_DASH}present"
    )


def test_continuing_series_with_explicit_end_year_shows_closed_range() -> None:
    assert _format_series_year_label(2016, 2017, SeriesStatus.CONTINUING) == f"2016{_EN_DASH}2017"


def test_ended_series_with_distinct_end_year_shows_closed_range() -> None:
    assert _format_series_year_label(2014, 2015, SeriesStatus.ENDED) == f"2014{_EN_DASH}2015"


def test_ended_series_without_end_year_uses_start_year_for_closed_range() -> None:
    assert _format_series_year_label(2014, None, SeriesStatus.ENDED) == "2014"


def test_unknown_series_without_end_year_does_not_show_present() -> None:
    assert _format_series_year_label(2014, None, SeriesStatus.UNKNOWN) == "2014"


def test_unknown_series_with_distinct_end_year_shows_closed_range() -> None:
    assert _format_series_year_label(2014, 2016, SeriesStatus.UNKNOWN) == f"2014{_EN_DASH}2016"


def test_continuing_series_with_same_start_and_end_year_collapses_range() -> None:
    assert _format_series_year_label(2016, 2016, SeriesStatus.CONTINUING) == "2016"


def test_missing_start_year_returns_unknown() -> None:
    assert _format_series_year_label(None, None, SeriesStatus.ENDED) == "Unknown"
