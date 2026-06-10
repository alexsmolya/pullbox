"""Characterization tests for alternate release import matching helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from pullbox.core.source_metadata import MetadataSignal, SourceMetadata
from pullbox.models.issue import IssueType
from pullbox.providers.base import SeriesSearchResult
from pullbox.services.import_alternate_release_matching import (
    evaluate_alternate_release_candidates,
    evaluate_alternate_signal_conflict,
)
from pullbox.services.import_match_candidates import build_candidate_diagnostics
from pullbox.services.semantic_matching import ImportPolicy, SemanticMatchEngine


def _make_search_result(
    *,
    provider_id: str,
    title: str,
    year_start: int | None,
    publisher: str | None = "DC Comics",
    issue_count: int | None = 1,
    status: str | None = "Ended",
) -> SeriesSearchResult:
    return SeriesSearchResult(
        provider_id=provider_id,
        title=title,
        year_start=year_start,
        publisher=publisher,
        issue_count=issue_count,
        status=status,
        cover_url=None,
        description=None,
    )


@pytest.mark.asyncio
async def test_evaluate_alternate_release_candidates_selects_exact_type_qualified_result() -> None:
    """The extracted helper keeps annual alternate-release selection behavior."""
    provider = AsyncMock()

    def _search_side_effect(query: str, year: int | None = None, **_: object):
        if query == "Immortal Thor 2024 Annual":
            return [
                _make_search_result(
                    provider_id="158867",
                    title="The Immortal Thor Annual",
                    year_start=2024,
                    publisher="Marvel",
                )
            ]
        return []

    provider.search_series.side_effect = _search_side_effect
    source_metadata = SourceMetadata(
        original_title="Immortal Thor Annual 001 (2024) (Digital).cbz",
        series_name="Immortal Thor",
        issue_number=1.0,
        year=2024,
        issue_type=IssueType.ANNUAL,
        diagnostics={
            "alternate_release_candidates": [
                {
                    "series_name": "Immortal Thor 2024 Annual",
                    "year": 2024,
                    "file_name": "Immortal Thor Annual 001 (2024) (Digital).cbz",
                    "signal": MetadataSignal.RELEASE_TITLE.value,
                    "issue_type": IssueType.ANNUAL.value,
                    "issue_type_qualified": True,
                }
            ]
        },
    )

    evaluation = await evaluate_alternate_release_candidates(
        provider=provider,
        source_metadata=source_metadata,
        raw_name="Immortal Thor",
        raw_year=2024,
        semantic_engine=SemanticMatchEngine(policy=ImportPolicy()),
        match_threshold=0.70,
        existing_top_candidates=[],
    )

    assert evaluation is not None
    assert evaluation.match is not None
    assert evaluation.match["cv_id"] == 158867
    assert evaluation.match["cv_match_method"] == "alternate_release_candidate"
    assert evaluation.diagnostics["selected_candidate"]["alternate_series_name"] == (
        "Immortal Thor 2024 Annual"
    )


@pytest.mark.asyncio
async def test_evaluate_alternate_signal_conflict_returns_review_diagnostics() -> None:
    """The extracted helper keeps ComicInfo-vs-release-title conflict behavior."""
    provider = AsyncMock()

    def _search_side_effect(query: str, year: int | None = None, **_: object):
        if query == "Chicken Devil":
            return [
                _make_search_result(
                    provider_id="139451",
                    title="Chicken Devil",
                    year_start=2021,
                    publisher="AfterShock Comics",
                    issue_count=4,
                )
            ]
        return []

    provider.search_series.side_effect = _search_side_effect
    source_metadata = SourceMetadata(
        original_title="Chicken Devil 004 (2022).cbz",
        series_name="Chicken Devils",
        issue_number=4.0,
        year=2022,
        signals={"series_name": MetadataSignal.COMICINFO},
        diagnostics={
            "alternate_release_candidates": [
                {
                    "series_name": "Chicken Devil",
                    "year": 2022,
                    "file_name": "Chicken Devil 004 (2022).cbz",
                    "signal": MetadataSignal.RELEASE_TITLE.value,
                }
            ]
        },
    )
    selected_result = _make_search_result(
        provider_id="145525",
        title="Chicken Devils",
        year_start=2022,
        publisher="AfterShock Comics",
        issue_count=4,
    )
    selected_candidate = build_candidate_diagnostics(
        raw_name="Chicken Devils",
        raw_year=2022,
        result=selected_result,
        threshold=0.70,
        score_override=0.98,
    )

    evaluation = await evaluate_alternate_signal_conflict(
        provider=provider,
        source_metadata=source_metadata,
        raw_name="Chicken Devils",
        raw_year=2022,
        semantic_engine=SemanticMatchEngine(policy=ImportPolicy()),
        match_threshold=0.70,
        selected_result=selected_result,
        selected_candidate=selected_candidate,
        selected_score=0.98,
        selected_match_method="exact_title_year",
        selected_match_type="exact",
        existing_top_candidates=[selected_candidate],
    )

    assert evaluation is not None
    assert evaluation.match is None
    assert evaluation.diagnostics["kind"] == "series_conflict"
    assert evaluation.diagnostics["reason"] == "metadata_signal_conflict"
    assert evaluation.diagnostics["selected_candidate"]["title"] == "Chicken Devils"
    assert evaluation.diagnostics["competing_candidate"]["title"] == "Chicken Devil"
