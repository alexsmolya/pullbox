"""Tests for ComicVine import candidate ranking helpers."""

from __future__ import annotations

from pullbox.core.source_metadata import SourceMetadata
from pullbox.providers.base import SeriesSearchResult
from pullbox.services.import_cv_candidate_ranking import (
    build_ranked_candidate_diagnostics,
    build_selected_candidate_summary,
    resolve_candidate_match_method,
)
from pullbox.services.semantic_matching import ImportPolicy, SemanticMatchEngine


def _series_result(
    *,
    provider_id: str,
    title: str,
    year_start: int | None,
    issue_count: int | None,
) -> SeriesSearchResult:
    return SeriesSearchResult(
        provider_id=provider_id,
        title=title,
        year_start=year_start,
        publisher="DC Comics",
        issue_count=issue_count,
        status=None,
        cover_url=None,
        description=None,
    )


def test_build_ranked_candidate_diagnostics_sorts_by_score_then_issue_count() -> None:
    source_metadata = SourceMetadata(
        original_title="Batman 001 (2016).cbz",
        series_name="Batman",
        year=2016,
    )
    semantic_engine = SemanticMatchEngine(policy=ImportPolicy())
    results = [
        _series_result(
            provider_id="3",
            title="Batman",
            year_start=2016,
            issue_count=10,
        ),
        _series_result(
            provider_id="2",
            title="Batman",
            year_start=2016,
            issue_count=85,
        ),
        _series_result(
            provider_id="1",
            title="Detective Comics",
            year_start=2016,
            issue_count=1000,
        ),
    ]

    diagnostics = build_ranked_candidate_diagnostics(
        raw_name="Batman",
        raw_year=2016,
        source_metadata=source_metadata,
        search_results=results,
        semantic_engine=semantic_engine,
        match_threshold=0.80,
    )

    assert [candidate["cv_id"] for candidate in diagnostics] == [2, 3, 1]
    assert diagnostics[0]["score"] == diagnostics[1]["score"]
    assert diagnostics[0]["issue_count"] == 85
    assert diagnostics[0]["match_type"] == "exact"


def test_resolve_candidate_match_method_preserves_current_threshold_semantics() -> None:
    assert (
        resolve_candidate_match_method(
            {"match_type": "exact", "score": 0.90},
            selected_year_delta=1,
        )
        == "exact_title_year"
    )
    assert (
        resolve_candidate_match_method(
            {"match_type": "exact", "score": 0.96},
            selected_year_delta=5,
        )
        == "exact_title_year"
    )
    assert (
        resolve_candidate_match_method(
            {"match_type": "fuzzy", "score": 0.96},
            selected_year_delta=0,
        )
        == "fuzzy_title"
    )


def test_build_selected_candidate_summary_preserves_diagnostic_shape() -> None:
    result = _series_result(
        provider_id="97508",
        title="Batman",
        year_start=2016,
        issue_count=85,
    )

    summary = build_selected_candidate_summary(
        result,
        score=0.87654,
        match_method="fuzzy_title",
        match_type="token_subset",
        year_delta=2,
        extra={
            "issue_year": 2018,
            "issue_year_delta": 2,
        },
    )

    assert summary == {
        "cv_id": 97508,
        "title": "Batman",
        "year": 2016,
        "publisher": "DC Comics",
        "issue_count": 85,
        "score": 0.8765,
        "score_pct": 88,
        "match_method": "fuzzy_title",
        "match_type": "token_subset",
        "year_delta": 2,
        "issue_year": 2018,
        "issue_year_delta": 2,
    }


def test_build_selected_candidate_summary_can_omit_year_delta() -> None:
    result = _series_result(
        provider_id="97508",
        title="Batman",
        year_start=2016,
        issue_count=85,
    )

    summary = build_selected_candidate_summary(
        result,
        score=0.95,
        match_method="exact_title_year",
        match_type="exact",
    )

    assert "year_delta" not in summary
