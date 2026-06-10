"""Series identity helpers for import deduplication."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

from pullbox.core.name_matcher import NameMatcher
from pullbox.core.type_semantics import series_types_compatible
from pullbox.models.series import SeriesType

if TYPE_CHECKING:
    from pullbox.core.collection_scanner import DiscoveredSeries

_matcher = NameMatcher()
_EXPANSION_SERIES_MATCH_TYPES = frozenset({"fuzzy", "starts_with", "token_subset"})


@dataclass
class DeduplicationResult:
    """Result of checking a discovered series against existing library."""

    discovered: DiscoveredSeries
    is_duplicate: bool
    existing_series_id: int | None = None
    existing_series_title: str | None = None


def is_same_series(
    candidate_name: str,
    candidate_year: int | None,
    candidate_series_type_or_existing_title: SeriesType | str | None,
    existing_title_or_year: str | int | None,
    existing_year_or_series_type: int | SeriesType | None = None,
    existing_series_type: SeriesType | None = None,
    *,
    similarity_threshold: float = 0.85,
) -> bool:
    """Return True if the candidate appears to be the same series."""
    if isinstance(candidate_series_type_or_existing_title, str) and not isinstance(
        candidate_series_type_or_existing_title, SeriesType
    ):
        candidate_series_type = None
        existing_title = candidate_series_type_or_existing_title
        existing_year = existing_title_or_year if isinstance(existing_title_or_year, int) else None
        resolved_existing_series_type = (
            existing_year_or_series_type
            if (
                isinstance(existing_year_or_series_type, SeriesType)
                or existing_year_or_series_type is None
            )
            else None
        )
    else:
        candidate_series_type = candidate_series_type_or_existing_title
        if not isinstance(existing_title_or_year, str):
            msg = "existing_title must be provided when candidate_series_type is supplied"
            raise TypeError(msg)
        existing_title = existing_title_or_year
        existing_year = (
            existing_year_or_series_type
            if isinstance(existing_year_or_series_type, int) or existing_year_or_series_type is None
            else None
        )
        resolved_existing_series_type = existing_series_type

    if (
        candidate_series_type is not None
        and resolved_existing_series_type is not None
        and not series_types_compatible(candidate_series_type, resolved_existing_series_type)
    ):
        return False

    norm_candidate = NameMatcher.normalize(candidate_name)
    norm_existing = NameMatcher.normalize(existing_title)

    result = _matcher.match(norm_candidate, norm_existing)
    similarity = result.similarity

    if similarity < similarity_threshold:
        return False
    if result.match_type in _EXPANSION_SERIES_MATCH_TYPES and _candidate_is_less_specific_title(
        norm_candidate,
        norm_existing,
    ):
        return False
    if result.match_type in _EXPANSION_SERIES_MATCH_TYPES and _candidate_is_more_specific_title(
        norm_candidate,
        norm_existing,
    ):
        return False
    if result.match_type == "fuzzy" and _candidate_is_parallel_subtitle_title(
        norm_candidate,
        norm_existing,
    ):
        return False

    if candidate_year is not None and existing_year is not None:
        return abs(candidate_year - existing_year) <= 1

    return True


def _candidate_is_less_specific_title(norm_candidate: str, norm_existing: str) -> bool:
    """Return True when the import title is only the base of a more specific title."""
    candidate_tokens = norm_candidate.split()
    existing_tokens = norm_existing.split()
    if not candidate_tokens or len(candidate_tokens) >= len(existing_tokens):
        return False

    candidate_set = set(candidate_tokens)
    existing_set = set(existing_tokens)
    if candidate_set < existing_set:
        return True

    return existing_tokens[: len(candidate_tokens)] == candidate_tokens


def _candidate_is_more_specific_title(norm_candidate: str, norm_existing: str) -> bool:
    """Return True when the import title expands an existing base-series title."""
    candidate_tokens = norm_candidate.split()
    existing_tokens = norm_existing.split()
    if not existing_tokens or len(candidate_tokens) <= len(existing_tokens):
        return False

    candidate_set = set(candidate_tokens)
    existing_set = set(existing_tokens)
    if existing_set < candidate_set:
        return True

    return candidate_tokens[: len(existing_tokens)] == existing_tokens


def _candidate_is_parallel_subtitle_title(norm_candidate: str, norm_existing: str) -> bool:
    """Return True for sibling one-shot/subtitle titles that only differ by subject."""
    candidate_tokens = norm_candidate.split()
    existing_tokens = norm_existing.split()
    if len(candidate_tokens) != len(existing_tokens) or len(candidate_tokens) < 4:
        return False

    shared_prefix_length = 0
    for candidate_token, existing_token in zip(candidate_tokens, existing_tokens, strict=True):
        if candidate_token != existing_token:
            break
        shared_prefix_length += 1

    if shared_prefix_length != len(candidate_tokens) - 1:
        return False

    candidate_tail = candidate_tokens[-1]
    existing_tail = existing_tokens[-1]
    if (
        not candidate_tail.isalpha()
        or not existing_tail.isalpha()
        or len(candidate_tail) < 3
        or len(existing_tail) < 3
    ):
        return False

    # Very similar suffixes are likely OCR/typo variants; unrelated suffixes are siblings.
    return SequenceMatcher(None, candidate_tail, existing_tail).ratio() < 0.80
