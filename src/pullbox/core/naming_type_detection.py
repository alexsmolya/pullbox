"""Comic issue and series type detection helpers used by naming flows."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape

# Type detection patterns for classifying comics from filename/tags.
_TYPE_DETECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("annual", re.compile(r"\bAnnual\b", re.IGNORECASE)),
    ("tpb", re.compile(r"\bTPB\b", re.IGNORECASE)),
    ("omnibus", re.compile(r"\bOmnibus\b", re.IGNORECASE)),
    ("compendium", re.compile(r"\bCompendium\b", re.IGNORECASE)),
    (
        "ogn",
        re.compile(r"\bOGN\b|\bOriginal\s+Graphic\s+Novel\b", re.IGNORECASE),
    ),
    ("gn", re.compile(r"\bGN\b|\bGraphic[\s.]Novel\b", re.IGNORECASE)),
    ("hc", re.compile(r"\bHardcover\b|\bHC\b", re.IGNORECASE)),
    ("one_shot", re.compile(r"\bOne[\s-]?Shot\b", re.IGNORECASE)),
    ("special", re.compile(r"\bSpecial\b", re.IGNORECASE)),
    ("deluxe", re.compile(r"\bDeluxe\b", re.IGNORECASE)),
    ("volume", re.compile(r"\bVol(?:ume)?\.?\s*\d+", re.IGNORECASE)),
]

# Patterns for detecting series type from CV volume titles.
# These check the title itself, not filenames; e.g. "Batman Annual" vs "Batman".
_SERIES_TYPE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("annual", re.compile(r"\bAnnuals?\b", re.IGNORECASE)),
    ("one_shot", re.compile(r"\bOne[\s-]?Shot\b", re.IGNORECASE)),
    ("omnibus", re.compile(r"\bOmnibus\b", re.IGNORECASE)),
    ("compendium", re.compile(r"\bCompendium\b", re.IGNORECASE)),
    (
        "graphic_novel",
        re.compile(r"\b(?:Original\s+)?Graphic\s+Novel\b", re.IGNORECASE),
    ),
    ("deluxe", re.compile(r"\bDeluxe\b", re.IGNORECASE)),
    ("tpb", re.compile(r"\bTPB\b|\bTrade\s+Paperback\b", re.IGNORECASE)),
    ("hardcover", re.compile(r"\bHardcover\b|\bHC\b", re.IGNORECASE)),
    (
        "special",
        re.compile(r"\bSpecials?\b(?!\s+Editions?\b)|\bAshcan\b", re.IGNORECASE),
    ),
    ("volume", re.compile(r"\bVol(?:ume)?\.?\s*\d+", re.IGNORECASE)),
    (
        "volume",
        re.compile(
            r"\b(?:Modern\s+Era\s+)?Epic\s+Collection\b|"
            r"\b(?:Complete|Ultimate)\s+Collection\b|"
            r"\bCollected\s+Edition\b|\bComplete\s+Series\b|"
            r"\bLibrary\s+Edition\b",
            re.IGNORECASE,
        ),
    ),
]

# Patterns to strip type qualifiers from a CV title to find the base series name.
_STRIP_TYPE_RE = re.compile(
    r"\s*\b(?:Annuals?|TPB|Trade\s+Paperback|Omnibus|Compendium|"
    r"Original\s+Graphic\s+Novel|OGN|Graphic\s+Novel|Hardcover|HC|One[\s-]?Shot|"
    r"Specials?(?!\s+Editions?\b)|Ashcan|Deluxe(?:\s+Edition)?|"
    r"(?:Modern\s+Era\s+)?Epic\s+Collection|(?:Complete|Ultimate)\s+Collection|"
    r"Collected\s+Edition|Complete\s+Series|Library\s+Edition|"
    r"Vol(?:ume)?\.?\s*\d+)\b\s*",
    re.IGNORECASE,
)

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


@dataclass(frozen=True, slots=True)
class SeriesTypeEvidence:
    """Explain the bounded semantic evidence used for a series classification."""

    series_type: str
    source: str
    signal: str | None = None


_DESCRIPTION_IDENTITY_PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    (
        "annual",
        "annual_identity",
        re.compile(
            r"^(?:an?\s+|this\s+|the\s+)?annual(?:s|\s+(?:issue|companion|special))?\b|"
            r"\bseries\s+of\s+annuals\b|\bannual\s+(?:for|of|to|from)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "one_shot",
        "one_shot_identity",
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
        "omnibus",
        "omnibus_identity",
        re.compile(
            r"^(?:an?\s+|this\s+|the\s+)?(?:complete\s+|hardcover\s+)?omnibus\b|"
            r"\bthis\s+omnibus\s+(?:collects|collecting|reprints|includes)\b|"
            r"\bseries\s+of\s+omnibus\s+collections\b",
            re.IGNORECASE,
        ),
    ),
    (
        "compendium",
        "compendium_identity",
        re.compile(
            r"^(?:an?\s+|this\s+|the\s+)?(?:complete\s+)?compendium\b|"
            r"\bthis\s+compendium\s+(?:collects|collecting|reprints|includes)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "graphic_novel",
        "graphic_novel_identity",
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
        "deluxe",
        "deluxe_identity",
        re.compile(
            r"^(?:an?\s+|this\s+|the\s+)?deluxe\s+"
            r"(?:oversized\s+)?(?:hardcover|edition|collection|trade\s+paperback)\b|"
            r"\bthis\s+deluxe\s+(?:edition|collection)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "special",
        "special_identity",
        re.compile(
            r"^(?:an?\s+|this\s+|the\s+)?special(?!\s+edition\b)\s+"
            r"(?:issue|one[\s-]?shot|ashcan|publication)\b|"
            r"^(?:an?\s+|this\s+|the\s+)?(?:holiday|seasonal|fcbd|souvenir)\s+special\b",
            re.IGNORECASE,
        ),
    ),
]

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
_GENERIC_COLLECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "leading_collects",
        re.compile(
            r"^(?:(?:reprints\s*/\s*)?collects?|collecting|reprints|compiles|gathers)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "collection_subject",
        re.compile(
            r"\b(?:this|the)\s+collection\s+"
            r"(?:collects|reprints|includes|contains|compiles|gathers)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "volume_subject",
        re.compile(
            r"\b(?:this|the)\s+(?:volume|book|edition)\s+"
            r"(?:collects|reprints|includes|contains|compiles|gathers)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "numbered_volume_subject",
        re.compile(
            r"^vol(?:ume)?\.?\s+[\w.-]+\s*(?::|-)?\s*"
            r"(?:collects|reprints|includes|contains|compiles|gathers)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "digital_collection",
        re.compile(r"\bdigital\s+collection\s+(?:collecting|of)\b", re.IGNORECASE),
    ),
    (
        "collected_in_this_volume",
        re.compile(
            r"\b(?:stories|issues|material)\s+(?:are\s+)?collected\s+in\s+this\s+volume\b",
            re.IGNORECASE,
        ),
    ),
]


def detect_issue_type(text: str) -> str:
    """Detect comic type from a filename or tag string."""
    for type_value, pattern in _TYPE_DETECTION_PATTERNS:
        if pattern.search(text):
            return type_value
    return "issue"


def detect_series_type(title: str) -> str:
    """Detect series type from a ComicVine volume title."""
    for type_value, pattern in _SERIES_TYPE_PATTERNS:
        if pattern.search(title):
            return type_value
    return "standard"


def detect_issue_type_from_metadata_title(title: str | None) -> str:
    """Detect explicit issue type from a provider title without release-name heuristics."""
    if not title:
        return "issue"
    if _TPB_REFERENCE_RE.search(title) and _HARDCOVER_REFERENCE_RE.search(title):
        return "volume"
    detected = detect_series_type(title)
    return {
        "standard": "issue",
        "graphic_novel": "gn",
        "hardcover": "hc",
    }.get(detected, detected)


def extract_base_series_title(title: str) -> str:
    """Strip type qualifiers from a title to get the base series name."""
    base = _STRIP_TYPE_RE.sub(" ", title).strip()
    base = re.sub(r"\s{2,}", " ", base).strip()
    base = re.sub(r"[\s:,\-]+$", "", base).strip()
    return base or title


def _normalize_description(description: str) -> str:
    """Return a whitespace-normalized, bounded window of provider prose."""
    raw = unescape(description)
    text = _HTML_TAG_RE.sub(" ", raw)
    return " ".join(text.split())[:_DESCRIPTION_WINDOW]


def detect_series_type_evidence_from_description(description: str) -> SeriesTypeEvidence:
    """Classify provider prose only when it self-identifies the publication format."""
    if not description:
        return SeriesTypeEvidence("standard", "default")

    normalized = _normalize_description(description)
    for series_type, signal, pattern in _DESCRIPTION_IDENTITY_PATTERNS:
        if pattern.search(normalized):
            return SeriesTypeEvidence(series_type, "description", signal)

    if _MIXED_BINDING_RE.search(normalized):
        return SeriesTypeEvidence("volume", "description", "multiple_binding_formats")

    has_tpb = _TPB_REFERENCE_RE.search(normalized) is not None
    has_hardcover = _HARDCOVER_REFERENCE_RE.search(normalized) is not None
    if has_tpb and has_hardcover:
        return SeriesTypeEvidence("volume", "description", "multiple_binding_formats")
    if _TPB_IDENTITY_RE.search(normalized):
        return SeriesTypeEvidence("tpb", "description", "tpb_identity")
    if _HARDCOVER_IDENTITY_RE.search(normalized):
        return SeriesTypeEvidence("hardcover", "description", "hardcover_identity")

    for signal, pattern in _GENERIC_COLLECTION_PATTERNS:
        if pattern.search(normalized):
            return SeriesTypeEvidence("volume", "description", signal)

    return SeriesTypeEvidence("standard", "default")


def detect_series_type_from_description(description: str) -> str:
    """Detect series type from bounded, contextual ComicVine description evidence."""
    return detect_series_type_evidence_from_description(description).series_type


def detect_series_type_from_issue_count(
    issue_count: int,
    year_start: int | None,
    *,
    current_year: int | None = None,
) -> str:
    """Retain the compatibility API while refusing count-only type guesses."""
    return "standard"


def classify_series_type_evidence(
    title: str,
    description: str | None = None,
    issue_count: int = 0,
    year_start: int | None = None,
) -> SeriesTypeEvidence:
    """Return the strongest trustworthy semantic evidence for a series type."""
    detected = detect_series_type(title)
    if detected != "standard":
        return SeriesTypeEvidence(detected, "title", "explicit_title")

    if description:
        evidence = detect_series_type_evidence_from_description(description)
        if evidence.series_type != "standard":
            return evidence

    return SeriesTypeEvidence("standard", "default")


def classify_series_type(
    title: str,
    description: str | None = None,
    issue_count: int = 0,
    year_start: int | None = None,
) -> str:
    """Classify from explicit title or description evidence, never issue count alone."""
    return classify_series_type_evidence(
        title,
        description=description,
        issue_count=issue_count,
        year_start=year_start,
    ).series_type
