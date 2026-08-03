"""Repair heuristic series types and their inherited issue types.

Revision ID: n9o0p1q2r345
Revises: m8n9o0p1q234
Create Date: 2026-08-02
"""

from __future__ import annotations

import re
from collections import defaultdict
from html import unescape
from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "n9o0p1q2r345"
down_revision: str | None = "m8n9o0p1q234"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SERIES_TO_ISSUE_TYPE = {
    "ANNUAL": "ANNUAL",
    "TPB": "TPB",
    "OMNIBUS": "OMNIBUS",
    "GRAPHIC_NOVEL": "GN",
    "HARDCOVER": "HC",
    "ONE_SHOT": "ONE_SHOT",
    "SPECIAL": "SPECIAL",
    "DELUXE": "DELUXE",
    "COMPENDIUM": "COMPENDIUM",
    "VOLUME": "VOLUME",
}
_ISSUE_TO_SERIES_TYPE = {
    "ANNUAL": "ANNUAL",
    "TPB": "TPB",
    "OMNIBUS": "OMNIBUS",
    "GN": "GRAPHIC_NOVEL",
    "OGN": "GRAPHIC_NOVEL",
    "HC": "HARDCOVER",
    "ONE_SHOT": "ONE_SHOT",
    "SPECIAL": "SPECIAL",
    "DELUXE": "DELUXE",
    "COMPENDIUM": "COMPENDIUM",
    "VOLUME": "VOLUME",
}
_COLLECTION_ISSUE_TYPES = frozenset(
    {"TPB", "OMNIBUS", "GN", "OGN", "HC", "DELUXE", "COMPENDIUM", "VOLUME"}
)
_EXPLICIT_IMPORT_METADATA_SOURCES = frozenset({"provisional_import", "import_placeholder"})
_UNTRUSTED_LEGACY_SERIES_TYPES = frozenset({"ONE_SHOT", "SPECIAL"})
_DESCRIPTION_WINDOW = 2048
_HTML_TAG_RE = re.compile(r"<[^<>]*>")
_TPB_REFERENCE_RE = re.compile(r"\b(?:trade\s+paperbacks?|tpbs?)\b", re.IGNORECASE)
_HARDCOVER_REFERENCE_RE = re.compile(
    r"\b(?:hardcovers?|hardbacks?|hcs?)\b",
    re.IGNORECASE,
)
_MIXED_BINDING_RE = re.compile(
    r"\b(?:hardcovers?|hardbacks?)\s*(?:/|and|or)\s*(?:trade\s+)?paperbacks?\b|"
    r"\b(?:trade\s+)?paperbacks?\s*(?:/|and|or)\s*(?:hardcovers?|hardbacks?)\b",
    re.IGNORECASE,
)
_TITLE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("ANNUAL", re.compile(r"\bAnnuals?\b", re.IGNORECASE)),
    ("ONE_SHOT", re.compile(r"\bOne[\s-]?Shot\b", re.IGNORECASE)),
    ("OMNIBUS", re.compile(r"\bOmnibus\b", re.IGNORECASE)),
    ("COMPENDIUM", re.compile(r"\bCompendium\b", re.IGNORECASE)),
    (
        "GRAPHIC_NOVEL",
        re.compile(r"\b(?:Original\s+)?Graphic\s+Novel\b", re.IGNORECASE),
    ),
    ("DELUXE", re.compile(r"\bDeluxe\b", re.IGNORECASE)),
    ("TPB", re.compile(r"\bTPB\b|\bTrade\s+Paperback\b", re.IGNORECASE)),
    ("HARDCOVER", re.compile(r"\bHardcover\b|\bHC\b", re.IGNORECASE)),
    (
        "SPECIAL",
        re.compile(r"\bSpecials?\b(?!\s+Editions?\b)|\bAshcan\b", re.IGNORECASE),
    ),
    ("VOLUME", re.compile(r"\bVol(?:ume)?\.?\s*\d+", re.IGNORECASE)),
    (
        "VOLUME",
        re.compile(
            r"\b(?:Modern\s+Era\s+)?Epic\s+Collection\b|"
            r"\b(?:Complete|Ultimate)\s+Collection\b|"
            r"\bCollected\s+Edition\b|\bComplete\s+Series\b|"
            r"\bLibrary\s+Edition\b",
            re.IGNORECASE,
        ),
    ),
)
_DESCRIPTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "ANNUAL",
        re.compile(
            r"^(?:an?\s+|this\s+|the\s+)?annual(?:s|\s+(?:issue|companion|special))?\b|"
            r"\bseries\s+of\s+annuals\b|\bannual\s+(?:for|of|to|from)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "ONE_SHOT",
        re.compile(
            r"^(?:an?\s+|this\s+|the\s+)?(?:digital\s+|promotional\s+)?"
            r"(?:special\s+)?one[\s-]?shot\b|"
            r"\b(?:is|was)\s+(?:an?\s+)?one[\s-]?shot\b|"
            r"^(?:an?\s+|this\s+|the\s+)?(?:one[\s-]off|standalone)\s+"
            r"(?:issue|story|comic)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "OMNIBUS",
        re.compile(
            r"^(?:an?\s+|this\s+|the\s+)?(?:complete\s+|hardcover\s+)?omnibus\b|"
            r"\bthis\s+omnibus\s+(?:collects|collecting|reprints|includes)\b|"
            r"\bseries\s+of\s+omnibus\s+collections\b",
            re.IGNORECASE,
        ),
    ),
    (
        "COMPENDIUM",
        re.compile(
            r"^(?:an?\s+|this\s+|the\s+)?(?:complete\s+)?compendium\b|"
            r"\bthis\s+compendium\s+(?:collects|collecting|reprints|includes)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "GRAPHIC_NOVEL",
        re.compile(
            r"^(?:an?\s+|this\s+|the\s+)?"
            r"(?:(?:original|digital|black(?:\s+and\s+white)?|full[\s-]?colou?r)\s+)?"
            r"graphic\s+novel(?:la)?s?\b|"
            r"^series\s+of\s+(?:original\s+)?graphic\s+novels?\b|"
            r"\b(?:is|was)\s+(?:an?\s+)?(?:original\s+)?graphic\s+novel\b|"
            r"\bgraphic\s+novel\s+adaptation\b",
            re.IGNORECASE,
        ),
    ),
    (
        "DELUXE",
        re.compile(
            r"^(?:an?\s+|this\s+|the\s+)?deluxe\s+"
            r"(?:oversized\s+)?(?:hardcover|edition|collection|trade\s+paperback)\b|"
            r"\bthis\s+deluxe\s+(?:edition|collection)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "SPECIAL",
        re.compile(
            r"^(?:an?\s+|this\s+|the\s+)?special(?!\s+edition\b)\s+"
            r"(?:issue|one[\s-]?shot|ashcan|publication)\b|"
            r"^(?:an?\s+|this\s+|the\s+)?(?:holiday|seasonal|fcbd|souvenir)\s+special\b",
            re.IGNORECASE,
        ),
    ),
)
_TPB_IDENTITY_RE = re.compile(
    r"^(?:an?\s+|this\s+|the\s+)?(?:series\s+of\s+)?(?:digital\s+)?"
    r"(?:trade\s+paperbacks?|tpbs?)\b|"
    r"\b(?:released|published|available|collected)\s+(?:into|as)\s+(?:an?\s+)?"
    r"(?:trade\s+paperbacks?|tpbs?)\b",
    re.IGNORECASE,
)
_HARDCOVER_IDENTITY_RE = re.compile(
    r"^(?:an?\s+|this\s+|the\s+)?(?:series\s+of\s+)?(?:digital\s+)?"
    r"(?:hardcovers?|hardbacks?|hcs?)\b|"
    r"\b(?:released|published|available|collected)\s+(?:into|as)\s+(?:an?\s+)?"
    r"(?:hardcovers?|hardbacks?|hcs?)\b|\bthis\s+hardcover\s+(?:collects|edition)\b",
    re.IGNORECASE,
)
_GENERIC_COLLECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"^(?:(?:reprints\s*/\s*)?collects?|collecting|reprints|compiles|gathers)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:this|the)\s+collection\s+"
        r"(?:collects|reprints|includes|contains|compiles|gathers)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:this|the)\s+(?:volume|book|edition)\s+"
        r"(?:collects|reprints|includes|contains|compiles|gathers)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^vol(?:ume)?\.?\s+[\w.-]+\s*(?::|-)?\s*"
        r"(?:collects|reprints|includes|contains|compiles|gathers)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bdigital\s+collection\s+(?:collecting|of)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:stories|issues|material)\s+(?:are\s+)?collected\s+in\s+this\s+volume\b",
        re.IGNORECASE,
    ),
)


def _classify_series_type(title: str, description: str | None) -> str:
    for series_type, pattern in _TITLE_PATTERNS:
        if pattern.search(title):
            return series_type
    if not description:
        return "STANDARD"

    normalized = " ".join(_HTML_TAG_RE.sub(" ", unescape(description)).split())[
        :_DESCRIPTION_WINDOW
    ]
    for series_type, pattern in _DESCRIPTION_PATTERNS:
        if pattern.search(normalized):
            return series_type
    if _MIXED_BINDING_RE.search(normalized):
        return "VOLUME"
    has_tpb = _TPB_REFERENCE_RE.search(normalized) is not None
    has_hardcover = _HARDCOVER_REFERENCE_RE.search(normalized) is not None
    if has_tpb and has_hardcover:
        return "VOLUME"
    if _TPB_IDENTITY_RE.search(normalized):
        return "TPB"
    if _HARDCOVER_IDENTITY_RE.search(normalized):
        return "HARDCOVER"
    if any(pattern.search(normalized) for pattern in _GENERIC_COLLECTION_PATTERNS):
        return "VOLUME"
    return "STANDARD"


def _detect_issue_type_from_metadata_title(title: str | None) -> str:
    if not title:
        return "ISSUE"
    if _TPB_REFERENCE_RE.search(title) and _HARDCOVER_REFERENCE_RE.search(title):
        return "VOLUME"
    series_type = _classify_series_type(title, None)
    return {
        "STANDARD": "ISSUE",
        "GRAPHIC_NOVEL": "GN",
        "HARDCOVER": "HC",
    }.get(series_type, series_type)


def _series_type_from_complete_issue_titles(issue_rows: list[sa.Row]) -> str | None:
    issue_types = [
        _detect_issue_type_from_metadata_title(str(issue_row.title) if issue_row.title else None)
        for issue_row in issue_rows
    ]
    if not issue_types or "ISSUE" in issue_types:
        return None
    distinct_types = set(issue_types)
    if len(distinct_types) == 1:
        return _ISSUE_TO_SERIES_TYPE.get(next(iter(distinct_types)))
    if distinct_types.issubset(_COLLECTION_ISSUE_TYPES):
        return "VOLUME"
    return None


def _repair_connection(bind: sa.Connection) -> None:
    series = sa.table(
        "series",
        sa.column("id", sa.Integer()),
        sa.column("title", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("series_type", sa.String()),
        sa.column("parent_series_id", sa.Integer()),
    )
    issues = sa.table(
        "issues",
        sa.column("id", sa.Integer()),
        sa.column("series_id", sa.Integer()),
        sa.column("title", sa.String()),
        sa.column("issue_type", sa.String()),
        sa.column("metadata_source", sa.String()),
    )

    rows = bind.execute(
        sa.select(
            series.c.id,
            series.c.title,
            series.c.description,
            series.c.series_type,
        )
    ).all()
    issue_rows_by_series: dict[int, list[sa.Row]] = defaultdict(list)
    for issue_row in bind.execute(
        sa.select(
            issues.c.id,
            issues.c.series_id,
            issues.c.title,
            issues.c.issue_type,
            issues.c.metadata_source,
        )
    ).all():
        issue_rows_by_series[int(issue_row.series_id)].append(issue_row)

    for row in rows:
        previous_type = str(row.series_type)
        repaired_type = _classify_series_type(
            str(row.title),
            str(row.description) if row.description else None,
        )
        issue_rows = issue_rows_by_series.get(int(row.id), [])
        if repaired_type == "STANDARD" and previous_type != "STANDARD":
            issue_consensus = _series_type_from_complete_issue_titles(issue_rows)
            if issue_consensus is not None:
                repaired_type = issue_consensus
            elif previous_type not in _UNTRUSTED_LEGACY_SERIES_TYPES:
                repaired_type = previous_type
        if repaired_type == previous_type:
            continue

        previous_inherited = _SERIES_TO_ISSUE_TYPE.get(previous_type)
        repaired_inherited = _SERIES_TO_ISSUE_TYPE.get(repaired_type, "ISSUE")
        for issue_row in issue_rows:
            current_issue_type = str(issue_row.issue_type)
            explicit_issue_type = _detect_issue_type_from_metadata_title(
                str(issue_row.title) if issue_row.title else None
            )
            if explicit_issue_type != "ISSUE":
                if current_issue_type in {"ISSUE", previous_inherited}:
                    bind.execute(
                        sa.update(issues)
                        .where(issues.c.id == issue_row.id)
                        .values(issue_type=explicit_issue_type)
                    )
                continue

            if (
                issue_row.metadata_source in _EXPLICIT_IMPORT_METADATA_SOURCES
                and current_issue_type != "ISSUE"
            ):
                continue
            was_previous_inheritance = (
                previous_inherited is not None and current_issue_type == previous_inherited
            )
            needs_new_inheritance = current_issue_type == "ISSUE" and repaired_inherited != "ISSUE"
            if was_previous_inheritance or needs_new_inheritance:
                bind.execute(
                    sa.update(issues)
                    .where(issues.c.id == issue_row.id)
                    .values(issue_type=repaired_inherited)
                )

        values: dict[str, object] = {"series_type": repaired_type}
        if repaired_type == "STANDARD":
            values["parent_series_id"] = None
        bind.execute(sa.update(series).where(series.c.id == row.id).values(**values))


def upgrade() -> None:
    """Apply the evidence-based type classifier to existing catalog rows."""
    _repair_connection(op.get_bind())


def downgrade() -> None:
    """The prior heuristic classifications cannot be reconstructed safely."""
    return None
