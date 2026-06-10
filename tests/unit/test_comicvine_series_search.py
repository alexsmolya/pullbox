"""Tests for shared ComicVine series search presentation helpers."""

from __future__ import annotations

from types import SimpleNamespace

from pullbox.ui.comicvine_series_search import (
    parse_comicvine_series_query,
    sort_comicvine_series_results,
)


def test_parse_series_query_extracts_trailing_start_year_hint() -> None:
    parsed = parse_comicvine_series_query("x-men 2024")

    assert parsed.raw_query == "x-men 2024"
    assert parsed.title_query == "x-men"
    assert parsed.year_hint == 2024


def test_parse_series_query_extracts_parenthesized_start_year_hint() -> None:
    parsed = parse_comicvine_series_query("x-men (2024)")

    assert parsed.title_query == "x-men"
    assert parsed.year_hint == 2024


def test_parse_series_query_does_not_treat_issue_or_title_numbers_as_year_hints() -> None:
    prog = parse_comicvine_series_query("2000AD prog 2482")
    historical_title = parse_comicvine_series_query("Marvel 1602")
    future_title = parse_comicvine_series_query("Marvel 2099")

    assert prog.title_query == "2000AD prog 2482"
    assert prog.year_hint is None
    assert historical_title.title_query == "Marvel 1602"
    assert historical_title.year_hint is None
    assert future_title.title_query == "Marvel 2099"
    assert future_title.year_hint is None


def test_parse_series_query_allows_older_real_start_years() -> None:
    parsed = parse_comicvine_series_query("Batman 1966")

    assert parsed.title_query == "Batman"
    assert parsed.year_hint == 1966


def test_relevance_sort_prioritizes_exact_title_and_year_hint() -> None:
    results = [
        {"title": "X-Men", "year_start": 2025, "comicvine_id": 170049},
        {"title": "Ultimate X-Men", "year_start": 2024, "comicvine_id": 160082},
        {"title": "X-Men", "year_start": 2024, "comicvine_id": 158814},
        {"title": "X-Men Unlimited Infinity Comic", "year_start": 2024, "comicvine_id": 149557},
    ]

    sorted_results = sort_comicvine_series_results(
        results,
        "relevance",
        query="X-Men",
        year_hint=2024,
    )

    assert [item["comicvine_id"] for item in sorted_results] == [
        158814,
        170049,
        149557,
        160082,
    ]


def test_relevance_sort_prioritizes_exact_title_without_year_hint() -> None:
    results = [
        {"title": "Daredevil/Punisher: The Devil's Trigger", "year_start": 2026, "comicvine_id": 1},
        {"title": "The Punisher", "year_start": 2026, "comicvine_id": 2},
        {"title": "Punisher War Journal", "year_start": 2006, "comicvine_id": 3},
    ]

    sorted_results = sort_comicvine_series_results(results, "relevance", query="Punisher")

    assert [item["comicvine_id"] for item in sorted_results] == [2, 3, 1]


def test_relevance_sort_supports_raw_provider_result_objects() -> None:
    results = [
        SimpleNamespace(provider_id="1", title="Daredevil/Punisher", year_start=2026),
        SimpleNamespace(provider_id="2", title="The Punisher", year_start=2026),
        SimpleNamespace(provider_id="3", title="Punisher War Journal", year_start=2006),
    ]

    sorted_results = sort_comicvine_series_results(results, "relevance", query="Punisher")

    assert [item.provider_id for item in sorted_results] == ["2", "3", "1"]


def test_relevance_sort_treats_leading_articles_as_exact_matches() -> None:
    results = [
        {"title": "Punisher War Journal", "year_start": 2006, "comicvine_id": 1},
        {"title": "The Punisher", "year_start": 2026, "comicvine_id": 2},
        {"title": "Daredevil/Punisher: The Devil's Trigger", "year_start": 2026, "comicvine_id": 3},
    ]

    sorted_results = sort_comicvine_series_results(results, "relevance", query="Punisher")

    assert [item["comicvine_id"] for item in sorted_results] == [2, 1, 3]


def test_relevance_sort_buckets_starts_with_contains_and_token_matches() -> None:
    results = [
        {"title": "Batman Gotham Adventures", "year_start": 1998, "comicvine_id": 1},
        {"title": "Gotham Batman Adventures", "year_start": 2024, "comicvine_id": 2},
        {"title": "Batman Adventures Gotham Special", "year_start": 2024, "comicvine_id": 3},
        {"title": "Gotham Central", "year_start": 2002, "comicvine_id": 4},
    ]

    sorted_results = sort_comicvine_series_results(
        results,
        "relevance",
        query="Batman Adventures",
    )

    assert [item["comicvine_id"] for item in sorted_results] == [3, 2, 1, 4]


def test_relevance_sort_keeps_exact_title_above_different_title_same_year() -> None:
    results = [
        {"title": "Ultimate X-Men", "year_start": 2024, "comicvine_id": 1},
        {"title": "X-Men Unlimited Infinity Comic", "year_start": 2024, "comicvine_id": 2},
        {"title": "X-Men", "year_start": 2025, "comicvine_id": 3},
    ]

    sorted_results = sort_comicvine_series_results(
        results,
        "relevance",
        query="X-Men",
        year_hint=2024,
    )

    assert [item["comicvine_id"] for item in sorted_results] == [3, 2, 1]


def test_relevance_sort_uses_provider_order_for_equal_relevance_ties() -> None:
    results = [
        {"title": "Batman Adventures", "year_start": 1992, "comicvine_id": 1},
        {"title": "Batman Adventures", "year_start": 1992, "comicvine_id": 2},
        {"title": "The Batman Adventures", "year_start": 1992, "comicvine_id": 3},
    ]

    sorted_results = sort_comicvine_series_results(results, "relevance", query="Batman Adventures")

    assert [item["comicvine_id"] for item in sorted_results] == [1, 2, 3]


def test_explicit_non_relevance_sorts_are_unchanged() -> None:
    results = [
        {"title": "Batman", "year_start": 1940, "issue_count": 713, "comicvine_id": 1},
        {"title": "Action Comics", "year_start": 1938, "issue_count": 904, "comicvine_id": 2},
        {"title": "Batman", "year_start": 2016, "issue_count": 136, "comicvine_id": 3},
    ]

    assert [
        item["comicvine_id"]
        for item in sort_comicvine_series_results(results, "-year_start", query="Batman")
    ] == [3, 1, 2]
    assert [
        item["comicvine_id"]
        for item in sort_comicvine_series_results(results, "year_start", query="Batman")
    ] == [2, 1, 3]
    assert [
        item["comicvine_id"]
        for item in sort_comicvine_series_results(results, "-issue_count", query="Batman")
    ] == [2, 1, 3]
    assert [
        item["comicvine_id"]
        for item in sort_comicvine_series_results(results, "title", query="Batman")
    ] == [2, 1, 3]
