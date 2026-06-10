"""ComicInfo field trust helpers."""

from __future__ import annotations

import re

_STALE_RETAILER_FIELD_RE = re.compile(
    r"\b(?:comixology|amazon|amzn)\b",
    re.IGNORECASE,
)


def references_stale_retailer(value: object) -> bool:
    """Return true when a ComicInfo field references dead retailer metadata."""
    if value is None:
        return False
    return bool(_STALE_RETAILER_FIELD_RE.search(str(value)))


def scrub_stale_retailer_value(value: object) -> object | None:
    """Drop stale Comixology/Amazon values while preserving other metadata."""
    if references_stale_retailer(value):
        return None
    return value
