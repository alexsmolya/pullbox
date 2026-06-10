"""Unit tests for import ComicVine candidate scoring helpers."""

from __future__ import annotations

from pullbox.core.source_metadata import SourceMetadata
from pullbox.providers.base import SeriesSearchResult
from pullbox.services.import_match_candidates import (
    build_ambiguous_series_conflict_diagnostics,
    build_candidate_diagnostics,
    build_signal_conflict_series_diagnostics,
    candidate_has_exact_title_match,
    candidate_has_precise_title_match,
    ranked_candidate_diagnostics,
    score_cv_result,
    select_ranked_candidate,
    select_year_tolerant_exact_title_candidate,
)


def _make_result(
    *,
    provider_id: str = "101",
    title: str = "Batman",
    year_start: int | None = 2016,
    publisher: str | None = "DC Comics",
    issue_count: int | None = 85,
) -> SeriesSearchResult:
    return SeriesSearchResult(
        provider_id=provider_id,
        title=title,
        year_start=year_start,
        publisher=publisher,
        issue_count=issue_count,
        status="Ended",
        cover_url=None,
        description=None,
    )


def test_score_cv_result_treats_matching_parenthesized_publisher_as_metadata() -> None:
    score = score_cv_result(
        "Coraline (Harper Collins)",
        2008,
        "Coraline",
        2008,
        "HarperCollins",
    )

    assert score >= 0.95


def test_score_cv_result_keeps_non_publisher_parenthetical_in_title() -> None:
    score = score_cv_result(
        "Coraline (The Graphic Novel)",
        2008,
        "Coraline",
        2008,
        "HarperCollins",
    )

    assert score < 0.95


def test_build_candidate_diagnostics_preserves_score_and_extra_semantic_details() -> None:
    diagnostics = build_candidate_diagnostics(
        raw_name="Batman",
        raw_year=2016,
        result=_make_result(provider_id="97508", title="Batman", year_start=2018),
        threshold=0.80,
        score_override=0.87,
        extra_diagnostics={"match_type": "exact"},
    )

    assert diagnostics["cv_id"] == 97508
    assert diagnostics["score"] == 0.87
    assert diagnostics["score_pct"] == 87
    assert diagnostics["year_delta"] == 2
    assert diagnostics["match_type"] == "exact"
    assert diagnostics["rejection_reasons"] == ["Year differs by 2"]


def test_candidate_title_match_predicates_follow_stabilized_match_type_sets() -> None:
    assert candidate_has_exact_title_match({"match_type": "exact"})
    assert candidate_has_exact_title_match({"match_type": "alternate"})
    assert candidate_has_exact_title_match({"match_type": "token_set"})
    assert not candidate_has_exact_title_match({"match_type": "starts_with"})

    assert candidate_has_precise_title_match({"match_type": "starts_with"})
    assert candidate_has_precise_title_match({"match_type": "token_subset"})
    assert not candidate_has_precise_title_match({"match_type": "fuzzy"})


def test_ranked_candidates_keep_score_first_then_precise_near_year_tiebreaks() -> None:
    fuzzy_high_score = {
        "cv_id": 1,
        "score": 0.92,
        "match_type": "fuzzy",
        "year_delta": 0,
        "issue_count": 6,
    }
    exact_same_score = {
        "cv_id": 2,
        "score": 0.90,
        "match_type": "exact",
        "year_delta": 1,
        "issue_count": 4,
    }
    fuzzy_same_score = {
        "cv_id": 3,
        "score": 0.90,
        "match_type": "fuzzy",
        "year_delta": 1,
        "issue_count": 30,
    }

    ranked = ranked_candidate_diagnostics([fuzzy_same_score, exact_same_score, fuzzy_high_score])

    assert [candidate["cv_id"] for candidate in ranked] == [1, 2, 3]


def test_select_ranked_candidate_obeys_threshold_and_exclusions() -> None:
    results = [
        _make_result(provider_id="1", title="Batman", issue_count=85),
        _make_result(provider_id="2", title="Batman", issue_count=30),
    ]
    candidates = [
        {"cv_id": 1, "score": 0.95, "match_type": "exact", "year_delta": 0},
        {"cv_id": 2, "score": 0.93, "match_type": "exact", "year_delta": 0},
    ]

    selected = select_ranked_candidate(
        candidate_diagnostics=candidates,
        search_results=results,
        match_threshold=0.80,
        excluded_candidate_ids={1},
    )

    assert selected is not None
    selected_candidate, selected_result = selected
    assert selected_candidate["cv_id"] == 2
    assert selected_result.provider_id == "2"


def test_select_year_tolerant_exact_title_candidate_prefers_exact_title_to_subtitle() -> None:
    current = {
        "cv_id": 1,
        "score": 0.91,
        "match_type": "starts_with",
        "year_delta": 0,
        "issue_count": 12,
    }
    exact = {
        "cv_id": 2,
        "score": 0.90,
        "match_type": "exact",
        "year_delta": 1,
        "issue_count": 4,
    }

    selected = select_year_tolerant_exact_title_candidate(
        source_metadata=SourceMetadata(
            original_title="King Dracula 004.cbz",
            series_name="King Dracula",
            issue_number=4,
        ),
        current_candidate=current,
        candidate_diagnostics=[current, exact],
        match_threshold=0.80,
    )

    assert selected == exact


def test_conflict_diagnostics_share_review_shape() -> None:
    selected = {"cv_id": 1, "title": "Chicken Devil"}
    competing = {"cv_id": 2, "title": "Chicken Devils"}
    top_candidates = [selected, competing]

    ambiguous = build_ambiguous_series_conflict_diagnostics(
        raw_name="Chicken Devil",
        raw_year=2021,
        match_threshold=0.80,
        selected_candidate=selected,
        competing_candidate=competing,
        top_candidates=top_candidates,
    )
    signal = build_signal_conflict_series_diagnostics(
        raw_name="Chicken Devil",
        raw_year=2021,
        match_threshold=0.80,
        selected_candidate=selected,
        competing_candidate=competing,
        top_candidates=top_candidates,
        selected_signal="comicinfo",
        competing_signal="release_title",
        signal_file_name="Chicken Devil - Hell Yeah.cbz",
    )

    assert ambiguous["reason"] == "ambiguous_candidates"
    assert ambiguous["normalized_query"] == "chicken devil"
    assert signal["reason"] == "metadata_signal_conflict"
    assert signal["selected_signal"] == "comicinfo"
    assert signal["signal_file_name"] == "Chicken Devil - Hell Yeah.cbz"
