"""Shared issue-title semantics for collection search and matching."""

from __future__ import annotations

import re

_COLLECTION_PREFIX_RE = re.compile(
    r"^(?P<label>vol(?:ume)?|book|part)\.?\s*#?(?P<number>\d+(?:\.\d+)?)"
    r"\s*(?::|[-\u2013\u2014])?\s*(?P<subtitle>.*)$",
    re.IGNORECASE,
)
_NUMBER_ONLY_TITLE_RE = re.compile(
    r"^(?:issue|no\.?|number|#|vol(?:ume)?\.?|book|part)?\s*#?\d+(?:\.\d+)?$",
    re.IGNORECASE,
)
_GENERIC_COLLECTION_TITLES = frozenset(
    {
        "gn",
        "graphic novel",
        "hardcover",
        "hc",
        "hc tpb",
        "issue",
        "ogn",
        "original graphic novel",
        "sc",
        "softcover",
        "tpb",
        "trade paperback",
        "vol",
        "volume",
    }
)


def meaningful_issue_title(value: str | None) -> str | None:
    """Return normalized title text only when it adds semantic search evidence."""
    title = re.sub(r"\s+", " ", value or "").strip()
    if not title:
        return None
    normalized = re.sub(r"[^a-z0-9]+", " ", title.casefold()).strip()
    if normalized in _GENERIC_COLLECTION_TITLES or _NUMBER_ONLY_TITLE_RE.fullmatch(title):
        return None

    prefix = _COLLECTION_PREFIX_RE.match(title)
    if prefix is not None and not prefix.group("subtitle").strip():
        return None
    return title


def collection_title_fragment(value: str | None) -> str | None:
    """Return a query-ready collection title fragment with canonical volume syntax."""
    title = meaningful_issue_title(value)
    if title is None:
        return None
    prefix = _COLLECTION_PREFIX_RE.match(title)
    if prefix is None:
        return title

    label = prefix.group("label").casefold()
    canonical_label = "Vol" if label.startswith("vol") else label.title()
    parts = [canonical_label, prefix.group("number")]
    subtitle = prefix.group("subtitle").strip()
    if subtitle:
        parts.append(subtitle)
    return " ".join(parts)


def collection_title_subtitle(value: str | None) -> str | None:
    """Return the distinctive subtitle portion of a meaningful collection title."""
    title = meaningful_issue_title(value)
    if title is None:
        return None
    prefix = _COLLECTION_PREFIX_RE.match(title)
    if prefix is not None:
        subtitle = prefix.group("subtitle").strip()
        return subtitle or None
    return title


def collection_title_number(value: str | None) -> str | None:
    """Return an explicit collection ordinal even when the title has no subtitle."""
    title = re.sub(r"\s+", " ", value or "").strip()
    if not title:
        return None
    prefix = _COLLECTION_PREFIX_RE.match(title)
    return prefix.group("number") if prefix is not None else None
