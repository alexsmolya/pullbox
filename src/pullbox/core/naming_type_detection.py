"""Comic issue and series type detection helpers used by naming flows."""

from __future__ import annotations

import re
from datetime import UTC, datetime

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
    ("tpb", re.compile(r"\bTPB\b|\bTrade\s+Paperback\b", re.IGNORECASE)),
    ("omnibus", re.compile(r"\bOmnibus\b", re.IGNORECASE)),
    ("compendium", re.compile(r"\bCompendium\b", re.IGNORECASE)),
    (
        "graphic_novel",
        re.compile(r"\b(?:Original\s+)?Graphic\s+Novel\b", re.IGNORECASE),
    ),
    ("hardcover", re.compile(r"\bHardcover\b|\bHC\b", re.IGNORECASE)),
    ("one_shot", re.compile(r"\bOne[\s-]?Shot\b", re.IGNORECASE)),
    ("special", re.compile(r"\bSpecials?\b", re.IGNORECASE)),
    ("deluxe", re.compile(r"\bDeluxe\b", re.IGNORECASE)),
    ("volume", re.compile(r"\bVol(?:ume)?\.?\s*\d+", re.IGNORECASE)),
]

# Patterns to strip type qualifiers from a CV title to find the base series name.
_STRIP_TYPE_RE = re.compile(
    r"\s*\b(?:Annuals?|TPB|Trade\s+Paperback|Omnibus|Compendium|"
    r"Original\s+Graphic\s+Novel|OGN|Graphic\s+Novel|Hardcover|HC|One[\s-]?Shot|"
    r"Specials?|Deluxe(?:\s+Edition)?|"
    r"Vol(?:ume)?\.?\s*\d+)\b\s*",
    re.IGNORECASE,
)

# Patterns for detecting series type from ComicVine descriptions.
# Order matters: more specific collection types before generic signals.
_DESCRIPTION_TYPE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("omnibus", re.compile(r"\bOmnibus\b", re.IGNORECASE)),
    ("compendium", re.compile(r"\bCompendium\b", re.IGNORECASE)),
    ("hardcover", re.compile(r"\bHardcover\b|\bHC\b", re.IGNORECASE)),
    ("deluxe", re.compile(r"\bDeluxe\b", re.IGNORECASE)),
    ("tpb", re.compile(r"\bCollects\b", re.IGNORECASE)),
    ("tpb", re.compile(r"\bTrade\s+Paperback\b|\bTPB\b|\bPaperback\b", re.IGNORECASE)),
    (
        "graphic_novel",
        re.compile(r"\b(?:Original\s+)?Graphic\s+Novel\b", re.IGNORECASE),
    ),
    ("one_shot", re.compile(r"\bOne[\s-]?Shot\b", re.IGNORECASE)),
    ("annual", re.compile(r"\bAnnual\b", re.IGNORECASE)),
    ("special", re.compile(r"\bSpecials?\b", re.IGNORECASE)),
]

# Words before "one-shot" that indicate the series is not actually a one-shot,
# such as "includes a one-shot bonus" or "following the one-shot story".
_ONE_SHOT_FALSE_POSITIVE_RE = re.compile(
    r"(?:includes|features|contains|following\s+the|after\s+the|"
    r"continued\s+from|preceding)\b.*\bone[\s-]?shot\b",
    re.IGNORECASE,
)


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


def extract_base_series_title(title: str) -> str:
    """Strip type qualifiers from a title to get the base series name."""
    base = _STRIP_TYPE_RE.sub(" ", title).strip()
    base = re.sub(r"\s{2,}", " ", base).strip()
    base = re.sub(r"[\s:,\-]+$", "", base).strip()
    return base or title


def detect_series_type_from_description(description: str) -> str:
    """Detect series type from a ComicVine description."""
    if not description:
        return "standard"

    truncated = description[:60]
    for type_value, pattern in _DESCRIPTION_TYPE_PATTERNS:
        if pattern.search(truncated):
            if type_value == "one_shot" and _ONE_SHOT_FALSE_POSITIVE_RE.search(description):
                return "standard"
            return type_value
    return "standard"


def detect_series_type_from_issue_count(
    issue_count: int,
    year_start: int | None,
    *,
    current_year: int | None = None,
) -> str:
    """Detect one-shot series from issue count and start-year heuristics."""
    if current_year is None:
        current_year = datetime.now(UTC).year

    if issue_count == 1 and year_start is not None and year_start < current_year:
        return "one_shot"

    return "standard"


def classify_series_type(
    title: str,
    description: str | None = None,
    issue_count: int = 0,
    year_start: int | None = None,
) -> str:
    """Three-tier cascade for series type detection."""
    detected = detect_series_type(title)
    if detected != "standard":
        return detected

    if description:
        detected = detect_series_type_from_description(description)
        if detected != "standard":
            return detected

    return detect_series_type_from_issue_count(issue_count, year_start)
