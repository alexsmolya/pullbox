"""ComicVine import candidate ranking helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pullbox.services.import_match_candidates import (
    EXACT_SERIES_MATCH_TYPES as _EXACT_SERIES_MATCH_TYPES,
)
from pullbox.services.import_match_candidates import (
    PRECISE_SERIES_MATCH_TYPES as _PRECISE_SERIES_MATCH_TYPES,
)
from pullbox.services.import_match_candidates import build_candidate_diagnostics

_EXACT_THRESHOLD = 0.95
_OMIT = object()

if TYPE_CHECKING:
    from pullbox.core.source_metadata import SourceMetadata
    from pullbox.providers.base import SeriesSearchResult
    from pullbox.services.semantic_matching import SemanticMatchEngine


def build_ranked_candidate_diagnostics(
    *,
    raw_name: str,
    raw_year: int | None,
    source_metadata: SourceMetadata,
    search_results: list[SeriesSearchResult],
    semantic_engine: SemanticMatchEngine,
    match_threshold: float,
) -> list[dict[str, Any]]:
    """Score provider search results and return diagnostics in ranked order."""
    candidate_diagnostics: list[dict[str, Any]] = []
    for result in search_results:
        decision = semantic_engine.score_series_search_result(
            metadata=source_metadata,
            candidate=result,
        )
        candidate_diagnostics.append(
            build_candidate_diagnostics(
                raw_name=raw_name,
                raw_year=raw_year,
                result=result,
                threshold=match_threshold,
                score_override=decision.score,
                extra_diagnostics=decision.diagnostics,
            )
        )

    candidate_diagnostics.sort(
        key=lambda candidate: (
            float(candidate.get("score", 0.0)),
            int(candidate.get("issue_count") or 0),
        ),
        reverse=True,
    )
    return candidate_diagnostics


def resolve_candidate_match_method(
    candidate: dict[str, Any],
    *,
    selected_year_delta: int | None,
    exact_threshold: float = _EXACT_THRESHOLD,
) -> str:
    """Return the persisted ComicVine match method for a selected candidate."""
    candidate_score = float(candidate.get("score", 0.0))
    candidate_match_type = str(candidate.get("match_type") or "")
    if (
        candidate_match_type in _EXACT_SERIES_MATCH_TYPES
        and (selected_year_delta is None or selected_year_delta <= 1)
    ) or (
        candidate_score >= exact_threshold and candidate_match_type in _PRECISE_SERIES_MATCH_TYPES
    ):
        return "exact_title_year"
    return "fuzzy_title"


def build_selected_candidate_summary(
    result: SeriesSearchResult,
    *,
    score: float,
    match_method: str,
    match_type: str,
    year_delta: int | object | None = _OMIT,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the shared selected-candidate diagnostics payload."""
    summary: dict[str, Any] = {
        "cv_id": int(result.provider_id),
        "title": result.title,
        "year": result.year_start,
        "publisher": result.publisher,
        "issue_count": result.issue_count,
        "score": round(score, 4),
        "score_pct": round(score * 100),
        "match_method": match_method,
        "match_type": match_type,
    }
    if year_delta is not _OMIT:
        summary["year_delta"] = year_delta
    if extra:
        summary.update(extra)
    return summary
