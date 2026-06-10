"""Shared issue/series type semantics for search, library matching, and import."""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pullbox.models.issue import IssueType
from pullbox.models.series import SeriesType

if TYPE_CHECKING:
    from pullbox.services.semantic_matching import WorkflowPolicy


class TypeFamily(enum.StrEnum):
    """Canonical type family used across workflows."""

    STANDARD = "standard_family"
    ISSUE_LIKE = "issue_like_family"
    COLLECTION = "collection_family"


_ISSUE_TYPE_FAMILIES: dict[IssueType, TypeFamily] = {
    IssueType.ISSUE: TypeFamily.STANDARD,
    IssueType.ANNUAL: TypeFamily.ISSUE_LIKE,
    IssueType.ONE_SHOT: TypeFamily.ISSUE_LIKE,
    IssueType.SPECIAL: TypeFamily.ISSUE_LIKE,
    IssueType.TPB: TypeFamily.COLLECTION,
    IssueType.HC: TypeFamily.COLLECTION,
    IssueType.DELUXE: TypeFamily.COLLECTION,
    IssueType.GN: TypeFamily.COLLECTION,
    IssueType.OGN: TypeFamily.COLLECTION,
    IssueType.OMNIBUS: TypeFamily.COLLECTION,
    IssueType.COMPENDIUM: TypeFamily.COLLECTION,
    IssueType.VOLUME: TypeFamily.COLLECTION,
}

_SERIES_TYPE_FAMILIES: dict[SeriesType, TypeFamily] = {
    SeriesType.STANDARD: TypeFamily.STANDARD,
    SeriesType.ANNUAL: TypeFamily.ISSUE_LIKE,
    SeriesType.ONE_SHOT: TypeFamily.ISSUE_LIKE,
    SeriesType.SPECIAL: TypeFamily.ISSUE_LIKE,
    SeriesType.TPB: TypeFamily.COLLECTION,
    SeriesType.HARDCOVER: TypeFamily.COLLECTION,
    SeriesType.DELUXE: TypeFamily.COLLECTION,
    SeriesType.GRAPHIC_NOVEL: TypeFamily.COLLECTION,
    SeriesType.OMNIBUS: TypeFamily.COLLECTION,
    SeriesType.COMPENDIUM: TypeFamily.COLLECTION,
    SeriesType.VOLUME: TypeFamily.COLLECTION,
}

_ISSUE_TO_SERIES_TYPE: dict[IssueType, SeriesType] = {
    IssueType.ISSUE: SeriesType.STANDARD,
    IssueType.ANNUAL: SeriesType.ANNUAL,
    IssueType.TPB: SeriesType.TPB,
    IssueType.OMNIBUS: SeriesType.OMNIBUS,
    IssueType.GN: SeriesType.GRAPHIC_NOVEL,
    IssueType.OGN: SeriesType.GRAPHIC_NOVEL,
    IssueType.HC: SeriesType.HARDCOVER,
    IssueType.ONE_SHOT: SeriesType.ONE_SHOT,
    IssueType.SPECIAL: SeriesType.SPECIAL,
    IssueType.DELUXE: SeriesType.DELUXE,
    IssueType.COMPENDIUM: SeriesType.COMPENDIUM,
    IssueType.VOLUME: SeriesType.VOLUME,
}

_SERIES_TO_ISSUE_TYPE: dict[SeriesType, IssueType] = {
    SeriesType.STANDARD: IssueType.ISSUE,
    SeriesType.ANNUAL: IssueType.ANNUAL,
    SeriesType.TPB: IssueType.TPB,
    SeriesType.OMNIBUS: IssueType.OMNIBUS,
    SeriesType.GRAPHIC_NOVEL: IssueType.GN,
    SeriesType.HARDCOVER: IssueType.HC,
    SeriesType.ONE_SHOT: IssueType.ONE_SHOT,
    SeriesType.SPECIAL: IssueType.SPECIAL,
    SeriesType.DELUXE: IssueType.DELUXE,
    SeriesType.COMPENDIUM: IssueType.COMPENDIUM,
    SeriesType.VOLUME: IssueType.VOLUME,
}

_COLLECTION_INTERCHANGE: frozenset[IssueType] = frozenset(
    {
        IssueType.TPB,
        IssueType.HC,
        IssueType.DELUXE,
        IssueType.GN,
        IssueType.OGN,
        IssueType.OMNIBUS,
        IssueType.COMPENDIUM,
        IssueType.VOLUME,
    }
)

_ISSUE_LIKE_TITLE_PATTERNS: dict[IssueType, re.Pattern[str]] = {
    IssueType.ANNUAL: re.compile(r"\bannual\b", re.IGNORECASE),
    IssueType.ONE_SHOT: re.compile(r"\bone[\s-]?shot\b", re.IGNORECASE),
    IssueType.SPECIAL: re.compile(r"\bspecial\b", re.IGNORECASE),
}


@dataclass(frozen=True, slots=True)
class TypeCompatibility:
    """Compatibility result for a parsed type vs target type."""

    compatible: bool
    mode: str
    lowers_confidence: bool = False
    allow_issue_number_fallback: bool = False
    prefer_volume_number: bool = False
    prefer_subtitle: bool = False


def issue_type_family(issue_type: IssueType) -> TypeFamily:
    """Return the canonical family for an issue type."""
    return _ISSUE_TYPE_FAMILIES[issue_type]


def series_type_family(series_type: SeriesType) -> TypeFamily:
    """Return the canonical family for a series type."""
    return _SERIES_TYPE_FAMILIES[series_type]


def canonical_series_type_for_issue_type(issue_type: IssueType) -> SeriesType:
    """Map an issue type onto the canonical series type."""
    return _ISSUE_TO_SERIES_TYPE[issue_type]


def canonical_issue_type_for_series_type(series_type: SeriesType) -> IssueType:
    """Map a series type onto the canonical issue type."""
    return _SERIES_TO_ISSUE_TYPE[series_type]


def series_types_compatible(candidate: SeriesType, existing: SeriesType) -> bool:
    """Return True when two series types should be treated as the same family."""
    if candidate == existing:
        return True
    return series_type_family(candidate) == series_type_family(existing)


def title_supports_issue_like_type(issue_type: IssueType, *titles: str | None) -> bool:
    """Return true when target-provided titles carry the requested issue-like marker."""
    pattern = _ISSUE_LIKE_TITLE_PATTERNS.get(issue_type)
    if pattern is None:
        return False
    return any(title and pattern.search(title) for title in titles)


def issue_type_compatibility(
    *,
    parsed_type: IssueType,
    wanted_type: IssueType,
    policy: WorkflowPolicy,
) -> TypeCompatibility:
    """Resolve parsed-vs-target issue type compatibility for a workflow policy."""
    parsed_family = issue_type_family(parsed_type)
    wanted_family = issue_type_family(wanted_type)

    if parsed_type == wanted_type:
        return TypeCompatibility(
            compatible=True,
            mode="exact",
            prefer_volume_number=parsed_family == TypeFamily.COLLECTION,
            prefer_subtitle=parsed_family == TypeFamily.COLLECTION,
        )

    if {parsed_type, wanted_type} <= {IssueType.ONE_SHOT, IssueType.SPECIAL}:
        return TypeCompatibility(
            compatible=True,
            mode="issue_like_family",
            lowers_confidence=True,
        )

    if parsed_type in _COLLECTION_INTERCHANGE and wanted_type in _COLLECTION_INTERCHANGE:
        return TypeCompatibility(
            compatible=True,
            mode="collection_family",
            lowers_confidence=True,
            prefer_volume_number=True,
            prefer_subtitle=True,
        )

    if (
        policy.allow_collection_issue_match_fallback
        and parsed_family == TypeFamily.COLLECTION
        and wanted_type == IssueType.ISSUE
    ):
        return TypeCompatibility(
            compatible=True,
            mode="collection_to_issue_fallback",
            lowers_confidence=True,
            allow_issue_number_fallback=True,
            prefer_volume_number=True,
            prefer_subtitle=True,
        )

    if (
        parsed_type == IssueType.ISSUE
        and wanted_family == TypeFamily.COLLECTION
        and policy.allow_standard_collection_inference
    ):
        return TypeCompatibility(
            compatible=True,
            mode="issue_to_collection_inference",
            lowers_confidence=True,
            prefer_subtitle=True,
        )

    if (
        parsed_family == TypeFamily.ISSUE_LIKE
        and wanted_type == IssueType.ISSUE
        and policy.allow_issue_like_standard_compatibility
        and parsed_type == IssueType.ONE_SHOT
    ):
        return TypeCompatibility(
            compatible=True,
            mode="issue_like_to_standard",
            lowers_confidence=True,
        )

    if (
        parsed_type == IssueType.ISSUE
        and wanted_family == TypeFamily.ISSUE_LIKE
        and policy.allow_issue_like_issue_inference
        and wanted_type == IssueType.ONE_SHOT
    ):
        return TypeCompatibility(
            compatible=True,
            mode="issue_inferred_issue_like",
            lowers_confidence=True,
        )

    return TypeCompatibility(compatible=False, mode="mismatch")
