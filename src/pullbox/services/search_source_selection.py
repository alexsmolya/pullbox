"""Select one search winner without coupling scoring to its transport."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from pullbox.services.search_evaluation import DEFAULT_MIN_SCORE, _select_best_validation
from pullbox.services.search_scoring import DEFAULT_MAX_SIZE_MB, DEFAULT_MIN_SIZE_MB

if TYPE_CHECKING:
    from pullbox.providers.base import ReleaseResult
    from pullbox.services.direct_search_coordinator import DirectValidatedCandidate
    from pullbox.services.release_validator import ValidationResult
    from pullbox.services.search_targets import IssueSearchOutcome
    from pullbox.services.search_types import SearchEvalKwargs


@dataclass(frozen=True, slots=True)
class SearchSourceSelection:
    """The highest-ranked candidate plus the adapter needed to acquire it."""

    source_kind: Literal["indexer", "direct"]
    release: ReleaseResult
    validation: ValidationResult
    direct_result: DirectValidatedCandidate | None = None


def select_search_source(
    outcome: IssueSearchOutcome,
    eval_kwargs: SearchEvalKwargs,
) -> SearchSourceSelection | None:
    """Rank indexer and direct matches with the existing deterministic scorer."""
    direct_matches = outcome.direct_outcome.matched if outcome.direct_outcome else ()
    if not direct_matches:
        if outcome.best_validation is None or outcome.best_release is None:
            return None
        return SearchSourceSelection(
            source_kind="indexer",
            release=outcome.best_release,
            validation=outcome.best_validation,
        )

    validations = [*outcome.matched, *(item.validation for item in direct_matches)]
    selected = _select_best_validation(
        validations,
        min_score=eval_kwargs.get("min_score", DEFAULT_MIN_SCORE),
        confidence_blend=eval_kwargs.get("confidence_blend", 0.40),
        min_size_mb=eval_kwargs.get("min_size_mb", DEFAULT_MIN_SIZE_MB),
        max_size_mb=eval_kwargs.get("max_size_mb", DEFAULT_MAX_SIZE_MB),
        preferred_format=eval_kwargs.get("preferred_format"),
        seeder_tiers=eval_kwargs.get("seeder_tiers"),
        score_weights=eval_kwargs.get("score_weights"),
        grabs_weight=eval_kwargs.get("grabs_weight", 0),
        pack_penalty=eval_kwargs.get("pack_penalty", -20),
        max_file_count=eval_kwargs.get("max_file_count", 5),
        preferred_language=eval_kwargs.get("preferred_language", "en"),
        digital_bonus=eval_kwargs.get("digital_bonus", 10),
    )
    if selected is None:
        return None
    direct_result = next(
        (item for item in direct_matches if item.validation is selected),
        None,
    )
    return SearchSourceSelection(
        source_kind="direct" if direct_result is not None else "indexer",
        release=selected.release,
        validation=selected,
        direct_result=direct_result,
    )
