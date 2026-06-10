"""ComicVine import candidate scoring and diagnostics helpers."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from pullbox.core.name_matcher import NameMatcher
from pullbox.core.type_semantics import TypeFamily, issue_type_family

if TYPE_CHECKING:
    from pullbox.core.source_metadata import SourceMetadata
    from pullbox.providers.base import SeriesSearchResult

PRECISE_SERIES_MATCH_TYPES = frozenset(
    {"exact", "alternate", "token_set", "starts_with", "token_subset"}
)
EXACT_SERIES_MATCH_TYPES = frozenset({"exact", "alternate", "token_set"})
SUBTITLE_SERIES_MATCH_TYPES = frozenset({"starts_with", "token_subset"})

_PAREN_SUFFIX_RE = re.compile(r"\s*\(([^)]+)\)\s*$")
_PUBLISHER_FORM_WORDS = frozenset(
    {
        "book",
        "books",
        "comic",
        "comics",
        "entertainment",
        "press",
        "publisher",
        "publishing",
        "studio",
        "studios",
    }
)

_matcher = NameMatcher()


def score_cv_result(
    raw_name: str,
    raw_year: int | None,
    cv_title: str,
    cv_year: int | None,
    cv_publisher: str | None,
) -> float:
    """Score a CV search result against a candidate. Returns 0.0-1.0."""
    norm_cv = NameMatcher.normalize(cv_title)

    raw_names = [raw_name]
    stripped_publisher_suffix = _strip_matching_parenthesized_publisher_suffix(
        raw_name,
        cv_publisher,
    )
    if stripped_publisher_suffix:
        raw_names.append(stripped_publisher_suffix)

    result = max(
        (_matcher.match(NameMatcher.normalize(candidate), norm_cv) for candidate in raw_names),
        key=lambda match: match.similarity,
    )
    title_score = result.similarity * 0.70

    year_score = 0.0
    if raw_year is not None and cv_year is not None:
        diff = abs(raw_year - cv_year)
        if diff == 0:
            year_score = 0.25
        elif diff == 1:
            year_score = 0.15
        elif diff <= 3:
            year_score = 0.05
    elif raw_year is None and cv_year is None:
        year_score = 0.0

    publisher_score = 0.05 if cv_publisher else 0.0

    return min(title_score + year_score + publisher_score, 1.0)


def _strip_matching_parenthesized_publisher_suffix(
    raw_name: str,
    cv_publisher: str | None,
) -> str | None:
    """Strip a trailing ``(Publisher)`` only when ComicVine confirms the publisher."""
    if not raw_name or not cv_publisher:
        return None
    match = _PAREN_SUFFIX_RE.search(raw_name)
    if not match:
        return None
    if _publisher_signature(match.group(1)) != _publisher_signature(cv_publisher):
        return None
    stripped = raw_name[: match.start()].strip()
    return stripped or None


def _publisher_signature(value: str) -> str:
    tokens = [
        token
        for token in NameMatcher.normalize(value).split()
        if token not in _PUBLISHER_FORM_WORDS
    ]
    return "".join(tokens)


def build_candidate_diagnostics(
    *,
    raw_name: str,
    raw_year: int | None,
    result: SeriesSearchResult,
    threshold: float,
    score_override: float | None = None,
    extra_diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return structured scoring details for a ComicVine candidate."""
    normalized_query = NameMatcher.normalize(raw_name)
    normalized_candidate = NameMatcher.normalize(result.title)
    title_similarity = _matcher.match(normalized_query, normalized_candidate).similarity
    total_score = (
        score_override
        if score_override is not None
        else score_cv_result(
            raw_name,
            raw_year,
            result.title,
            result.year_start,
            result.publisher,
        )
    )

    rejection_reasons: list[str] = []
    if total_score < threshold:
        rejection_reasons.append(f"Below {(threshold * 100):.0f}% threshold")
    if raw_year is not None and result.year_start is not None:
        year_delta = abs(raw_year - result.year_start)
        if year_delta > 1:
            rejection_reasons.append(f"Year differs by {year_delta}")
    else:
        year_delta = None
    if not rejection_reasons:
        rejection_reasons.append("Outranked by a stronger candidate")

    return {
        "cv_id": int(result.provider_id),
        "title": result.title,
        "normalized_title": normalized_candidate,
        "year": result.year_start,
        "publisher": result.publisher,
        "issue_count": result.issue_count,
        "score": round(total_score, 4),
        "score_pct": round(total_score * 100),
        "title_similarity": round(title_similarity, 4),
        "title_similarity_pct": round(title_similarity * 100),
        "year_delta": year_delta,
        "rejection_reasons": rejection_reasons,
        **(extra_diagnostics or {}),
    }


def candidate_has_precise_title_match(candidate: dict[str, Any]) -> bool:
    """Return True when a candidate matched on title semantics stronger than fuzzy similarity."""
    return str(candidate.get("match_type") or "") in PRECISE_SERIES_MATCH_TYPES


def candidate_has_exact_title_match(candidate: dict[str, Any]) -> bool:
    """Return True when a candidate title matches without subtitle/fuzzy expansion."""
    return str(candidate.get("match_type") or "") in EXACT_SERIES_MATCH_TYPES


def candidate_cv_id(candidate: dict[str, Any]) -> int | None:
    try:
        return int(candidate.get("cv_id") or 0)
    except (TypeError, ValueError):
        return None


def _candidate_selection_key(
    candidate: dict[str, Any],
) -> tuple[float, bool, bool, float, int, int]:
    """Rank candidates for automatic matching after score calculation."""
    year_delta_raw = candidate.get("year_delta")
    try:
        year_delta = int(year_delta_raw) if year_delta_raw is not None else 9999
    except (TypeError, ValueError):
        year_delta = 9999
    near_year = year_delta <= 1
    return (
        float(candidate.get("score", 0.0)),
        near_year and candidate_has_exact_title_match(candidate),
        near_year and candidate_has_precise_title_match(candidate),
        float(candidate.get("shape_adjustment") or 0.0),
        -year_delta,
        int(candidate.get("issue_count") or 0),
    )


def ranked_candidate_diagnostics(
    candidate_diagnostics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return sorted(candidate_diagnostics, key=_candidate_selection_key, reverse=True)


def select_ranked_candidate(
    *,
    candidate_diagnostics: list[dict[str, Any]],
    search_results: list[SeriesSearchResult],
    match_threshold: float,
    excluded_candidate_ids: set[int] | None = None,
) -> tuple[dict[str, Any], SeriesSearchResult] | None:
    excluded_candidate_ids = excluded_candidate_ids or set()
    results_by_id: dict[int, SeriesSearchResult] = {}
    for result in search_results:
        try:
            results_by_id[int(result.provider_id)] = result
        except (TypeError, ValueError):
            continue

    for candidate in ranked_candidate_diagnostics(candidate_diagnostics):
        candidate_id = candidate_cv_id(candidate)
        if candidate_id is None or candidate_id in excluded_candidate_ids:
            continue
        if float(candidate.get("score", 0.0)) < match_threshold:
            continue
        matched_result = results_by_id.get(candidate_id)
        if matched_result is not None:
            return candidate, matched_result
    return None


def candidate_is_year_sensitive_expansion(candidate: dict[str, Any]) -> bool:
    """Return True when a candidate used subtitle expansion and needs year caution."""
    return str(candidate.get("match_type") or "") in SUBTITLE_SERIES_MATCH_TYPES


def candidate_issue_number_is_covered(
    *,
    source_metadata: SourceMetadata,
    candidate: dict[str, Any],
) -> bool:
    """Return True when an explicit source issue number fits the candidate series."""
    if source_metadata.issue_number is None:
        return False
    issue_count = candidate.get("issue_count")
    if issue_count is None:
        return False
    try:
        return float(source_metadata.issue_number) <= float(issue_count)
    except (TypeError, ValueError):
        return False


def _normalized_title_tokens(candidate: dict[str, Any]) -> set[str]:
    normalized_title = str(candidate.get("normalized_title") or "").strip()
    if not normalized_title:
        normalized_title = NameMatcher.normalize(str(candidate.get("title") or ""))
    return {token for token in normalized_title.split() if token}


def _candidate_contains_normalized_text(candidate: dict[str, Any], value: str) -> bool:
    expected_tokens = {
        token for token in NameMatcher.normalize(value).split() if token and not token.isdigit()
    }
    return bool(expected_tokens) and expected_tokens.issubset(_normalized_title_tokens(candidate))


def candidate_is_volume_subtitle_correlated(
    *,
    source_metadata: SourceMetadata,
    candidate: dict[str, Any],
) -> bool:
    """Return true when a collection candidate title validates the filename subtitle hint."""
    if issue_type_family(source_metadata.issue_type) != TypeFamily.COLLECTION:
        return False
    hint = source_metadata.diagnostics.get("volume_subtitle_hint")
    if not isinstance(hint, dict):
        return False
    base_series = str(hint.get("base_series") or "").strip()
    subtitle = str(hint.get("subtitle") or "").strip()
    return _candidate_contains_normalized_text(
        candidate,
        base_series,
    ) and _candidate_contains_normalized_text(candidate, subtitle)


def candidate_is_volume_subtitle_base_competitor(
    *,
    source_metadata: SourceMetadata,
    candidate: dict[str, Any],
) -> bool:
    """Return true when an exact competitor is only the base title from a volume hint."""
    hint = source_metadata.diagnostics.get("volume_subtitle_hint")
    if not isinstance(hint, dict):
        return False
    base_series = str(hint.get("base_series") or "").strip()
    return bool(base_series) and NameMatcher.normalize(
        str(candidate.get("title") or "")
    ) == NameMatcher.normalize(base_series)


def should_keep_subtitle_correlated_winner(
    *,
    source_metadata: SourceMetadata,
    selected_candidate: dict[str, Any],
    competing_candidate: dict[str, Any],
) -> bool:
    """Avoid false conflicts when a collection subtitle proves the selected candidate."""
    return candidate_is_volume_subtitle_correlated(
        source_metadata=source_metadata,
        candidate=selected_candidate,
    ) and candidate_is_volume_subtitle_base_competitor(
        source_metadata=source_metadata,
        candidate=competing_candidate,
    )


def select_year_tolerant_exact_title_candidate(
    *,
    source_metadata: SourceMetadata,
    current_candidate: dict[str, Any],
    candidate_diagnostics: list[dict[str, Any]],
    match_threshold: float,
) -> dict[str, Any] | None:
    """Prefer exact titles within year tolerance over subtitle matches with exact years."""
    if not candidate_is_year_sensitive_expansion(current_candidate):
        return None

    candidates = [
        candidate
        for candidate in candidate_diagnostics
        if candidate_has_exact_title_match(candidate)
        and float(candidate.get("score", 0.0)) >= match_threshold
        and (
            candidate.get("year_delta") is None
            or int(candidate.get("year_delta") or 0) <= 1
            or candidate_issue_number_is_covered(
                source_metadata=source_metadata,
                candidate=candidate,
            )
        )
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda candidate: (
            -int(candidate.get("year_delta") or 0),
            float(candidate.get("score", 0.0)),
            int(candidate.get("issue_count") or 0),
        ),
    )


def build_ambiguous_series_conflict_diagnostics(
    *,
    raw_name: str,
    raw_year: int | None,
    match_threshold: float,
    selected_candidate: dict[str, Any],
    competing_candidate: dict[str, Any],
    top_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return review diagnostics for a near-tie ComicVine candidate conflict."""
    return {
        "kind": "series_conflict",
        "reason": "ambiguous_candidates",
        "raw_name": raw_name,
        "raw_year": raw_year,
        "normalized_query": NameMatcher.normalize(raw_name),
        "threshold": round(match_threshold, 4),
        "selected_candidate": selected_candidate,
        "competing_candidate": competing_candidate,
        "top_candidates": top_candidates,
    }


def build_signal_conflict_series_diagnostics(
    *,
    raw_name: str,
    raw_year: int | None,
    match_threshold: float,
    selected_candidate: dict[str, Any],
    competing_candidate: dict[str, Any],
    top_candidates: list[dict[str, Any]],
    selected_signal: str,
    competing_signal: str,
    signal_file_name: str | None,
) -> dict[str, Any]:
    """Return review diagnostics when two strong source signals disagree on the series."""
    diagnostics = build_ambiguous_series_conflict_diagnostics(
        raw_name=raw_name,
        raw_year=raw_year,
        match_threshold=match_threshold,
        selected_candidate=selected_candidate,
        competing_candidate=competing_candidate,
        top_candidates=top_candidates,
    )
    diagnostics.update(
        {
            "reason": "metadata_signal_conflict",
            "selected_signal": selected_signal,
            "competing_signal": competing_signal,
            "signal_file_name": signal_file_name,
        }
    )
    return diagnostics
