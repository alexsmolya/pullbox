"""Intervention filter normalization and display metadata helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from typing import cast as typing_cast

from sqlalchemy import ColumnElement, case, func, true

from pullbox.models.indexer import IndexerConfig
from pullbox.models.issue import Issue
from pullbox.models.pending_match import PendingMatch, PendingMatchStatus

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import datetime

INTERVENTION_TABS = {"queue", "history"}
INTERVENTION_CONFIDENCE_FILTERS = {"high", "medium", "low"}
INTERVENTION_PROTOCOL_FILTERS = {"usenet", "torrent"}
INTERVENTION_REASON_LABELS = {
    "fuzzy_series": "Fuzzy series match",
    "issue_mismatch": "Issue mismatch",
    "year_mismatch": "Year mismatch",
    "type_mismatch": "Type mismatch",
    "size_warning": "Size warning",
    "needs_review": "Needs review",
}
INTERVENTION_REASON_FILTERS = {key for key in INTERVENTION_REASON_LABELS if key != "needs_review"}
INTERVENTION_OUTCOME_FILTERS = {"approved", "rejected", "expired"}
INTERVENTION_HISTORY_SORT_OPTIONS = {
    "title",
    "issue",
    "outcome",
    "confidence",
    "protocol",
    "resolved_at",
}


def normalize_intervention_tab(tab: str | None) -> str:
    """Return a valid intervention workspace tab."""
    normalized = (tab or "").strip().lower()
    if normalized in INTERVENTION_TABS:
        return normalized
    return "queue"


def normalize_intervention_confidence_filter(confidence: str | None) -> str:
    """Return a valid intervention confidence filter."""
    normalized = (confidence or "").strip().lower()
    if normalized in INTERVENTION_CONFIDENCE_FILTERS:
        return normalized
    return ""


def normalize_intervention_reason_filter(reason: str | None) -> str:
    """Return a valid intervention review-reason filter."""
    normalized = (reason or "").strip().lower()
    if normalized in INTERVENTION_REASON_FILTERS:
        return normalized
    return ""


def normalize_intervention_protocol_filter(protocol: str | None) -> str:
    """Return a valid intervention protocol filter."""
    normalized = (protocol or "").strip().lower()
    if normalized in INTERVENTION_PROTOCOL_FILTERS:
        return normalized
    return ""


def normalize_intervention_outcome_filter(outcome: str | None) -> str:
    """Return a valid intervention history outcome filter."""
    normalized = (outcome or "").strip().lower()
    if normalized in INTERVENTION_OUTCOME_FILTERS:
        return normalized
    return ""


def normalize_intervention_history_sort(sort: str | None) -> str:
    """Return a valid intervention history sort value."""
    if not sort:
        return "-resolved_at"
    field = sort.lstrip("-")
    if field not in INTERVENTION_HISTORY_SORT_OPTIONS:
        return "-resolved_at"
    return f"-{field}" if sort.startswith("-") else field


def intervention_source_expr() -> ColumnElement[str]:
    """Return the user-facing source label used by intervention filters."""
    return typing_cast(
        "ColumnElement[str]",
        func.coalesce(
            IndexerConfig.name,
            PendingMatch.match_details["indexer_name"].as_string(),
            "Unknown",
        ),
    )


def intervention_review_reason_codes(match_details: Mapping[str, object] | None) -> list[str]:
    """Return ordered review reasons derived from pending-match details."""
    details = match_details or {}
    reasons: list[str] = []

    if str(details.get("series_match_type") or "").strip().lower() == "fuzzy":
        reasons.append("fuzzy_series")
    if details.get("issue_match") is False:
        reasons.append("issue_mismatch")
    if details.get("year_match") is False:
        reasons.append("year_mismatch")
    if details.get("type_match") is False:
        reasons.append("type_mismatch")
    if details.get("size_warning"):
        reasons.append("size_warning")

    return reasons or ["needs_review"]


def intervention_review_reason_summary(reason_codes: Sequence[str]) -> str:
    """Compress derived review reasons into one scannable queue summary line."""
    labels = [INTERVENTION_REASON_LABELS.get(code, "Needs review") for code in reason_codes]
    if not labels:
        return "Needs review"
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]} · {labels[1]}"
    return f"{labels[0]} · {labels[1]} +{len(labels) - 2}"


def intervention_protocol_label(is_torrent: bool) -> str:
    """Return the human-readable protocol label for a pending match."""
    return "Torrent" if is_torrent else "Usenet"


def intervention_outcome_label(status: str) -> str:
    """Return a human-readable intervention history outcome label."""
    normalized = (status or "").strip().lower()
    if normalized == PendingMatchStatus.APPROVED.value:
        return "Approved"
    if normalized == PendingMatchStatus.REJECTED.value:
        return "Rejected"
    if normalized == PendingMatchStatus.EXPIRED.value:
        return "Expired"
    return normalized.replace("_", " ").title() or "Unknown"


def intervention_match_type_label(match_details: Mapping[str, object] | None) -> str:
    """Return the human-readable match quality label."""
    details = match_details or {}
    match_type = str(details.get("series_match_type") or "").strip().lower()
    if match_type == "exact":
        return "Exact series match"
    if match_type == "fuzzy":
        return "Fuzzy series match"
    return "Needs review"


def intervention_review_reason_clause(reason: str) -> ColumnElement[bool]:
    """Return the SQL clause for a derived review-reason filter."""
    if reason == "fuzzy_series":
        return typing_cast(
            "ColumnElement[bool]",
            PendingMatch.match_details["series_match_type"].as_string() == "fuzzy",
        )
    if reason == "issue_mismatch":
        return typing_cast(
            "ColumnElement[bool]",
            PendingMatch.match_details["issue_match"].as_boolean().is_(False),
        )
    if reason == "year_mismatch":
        return typing_cast(
            "ColumnElement[bool]",
            PendingMatch.match_details["year_match"].as_boolean().is_(False),
        )
    if reason == "type_mismatch":
        return typing_cast(
            "ColumnElement[bool]",
            PendingMatch.match_details["type_match"].as_boolean().is_(False),
        )
    if reason == "size_warning":
        return typing_cast(
            "ColumnElement[bool]",
            PendingMatch.match_details["size_warning"].as_string().is_not(None),
        )
    return typing_cast("ColumnElement[bool]", true())


def intervention_resolved_expr() -> ColumnElement[datetime]:
    """Return the effective resolved timestamp for intervention history."""
    return func.coalesce(PendingMatch.resolved_at, PendingMatch.updated_at)


def get_intervention_history_order_by(sort: str) -> list[ColumnElement[object]]:
    """Build stable ORDER BY clauses for intervention history."""
    normalized_sort = normalize_intervention_history_sort(sort)
    sort_desc = normalized_sort.startswith("-")
    sort_field = normalized_sort[1:] if sort_desc else normalized_sort

    outcome_sort = case(
        (PendingMatch.status == PendingMatchStatus.APPROVED, 0),
        (PendingMatch.status == PendingMatchStatus.REJECTED, 1),
        (PendingMatch.status == PendingMatchStatus.EXPIRED, 2),
        else_=3,
    )
    protocol_sort = case((PendingMatch.is_torrent.is_(True), 0), else_=1)
    resolved_sort = intervention_resolved_expr()

    sort_map: dict[str, ColumnElement[object]] = {
        "title": typing_cast("ColumnElement[object]", PendingMatch.release_title),
        "issue": typing_cast("ColumnElement[object]", Issue.issue_number),
        "outcome": typing_cast("ColumnElement[object]", outcome_sort),
        "confidence": typing_cast("ColumnElement[object]", PendingMatch.confidence),
        "protocol": typing_cast("ColumnElement[object]", protocol_sort),
        "resolved_at": typing_cast("ColumnElement[object]", resolved_sort),
    }

    primary = sort_map.get(sort_field, resolved_sort)
    if sort_desc:
        primary = typing_cast("ColumnElement[object]", primary.desc())
    else:
        primary = typing_cast("ColumnElement[object]", primary.asc())

    return [
        primary,
        typing_cast("ColumnElement[object]", resolved_sort.desc()),
        typing_cast("ColumnElement[object]", PendingMatch.id.desc()),
    ]


def build_intervention_item_meta(pending_match: Any) -> dict[str, object]:
    """Build derived display metadata for intervention queue/history items."""
    details = getattr(pending_match, "match_details", None) or {}
    reason_codes = intervention_review_reason_codes(details)
    reason_labels = [INTERVENTION_REASON_LABELS.get(code, "Needs review") for code in reason_codes]
    similarity = details.get("series_similarity")
    similarity_pct = None
    if isinstance(similarity, (float, int)):
        similarity_pct = round(float(similarity) * 100, 1)

    indexer = getattr(pending_match, "indexer", None)
    source_label = (
        indexer.name if indexer is not None else str(details.get("indexer_name") or "Unknown")
    )

    return {
        "protocol_label": intervention_protocol_label(bool(pending_match.is_torrent)),
        "outcome_label": intervention_outcome_label(str(pending_match.status)),
        "review_reason_codes": reason_codes,
        "review_reason_labels": reason_labels,
        "review_reason_summary": intervention_review_reason_summary(reason_codes),
        "match_type_label": intervention_match_type_label(details),
        "similarity_pct": similarity_pct,
        "source_label": source_label.strip() or "Unknown",
        "rejection_reason": str(details.get("rejection_reason") or "").strip(),
    }
