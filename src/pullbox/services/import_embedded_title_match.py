"""Helpers for one-issue provider volumes whose issue number lives in the title."""

from __future__ import annotations

import re

from pullbox.core.name_matcher import NameMatcher


def embedded_issue_number_title_match(
    *,
    source_series_name: str | None,
    original_title: str | None,
    target_series_title: str | None,
    issue_number: float | None,
) -> bool:
    """Return True when removing an embedded issue number makes titles align.

    Some provider volumes are modeled as one-issue series whose title contains the
    apparent issue number, for example ``Episode 40 - Captured``. In that case a
    source file parsed as issue 40 can safely target provider issue #1 only when
    the matched provider title becomes the parsed source series after removing 40.
    """
    issue_token = _integer_issue_token(issue_number)
    if issue_token is None or issue_token == "1":
        return False

    source_norm = NameMatcher.normalize(source_series_name or "")
    original_norm = NameMatcher.normalize(original_title or "")
    target_norm = NameMatcher.normalize(target_series_title or "")
    if not source_norm or not original_norm or not target_norm:
        return False
    if not _contains_issue_token(original_norm, issue_token, allow_leading_zeroes=True):
        return False
    if not _contains_issue_token(target_norm, issue_token, allow_leading_zeroes=False):
        return False
    if not _issue_token_has_following_title_text(target_norm, issue_token):
        return False

    target_without_issue = _remove_issue_token(target_norm, issue_token)
    return target_without_issue == source_norm


def _integer_issue_token(issue_number: float | None) -> str | None:
    if issue_number is None:
        return None
    if abs(issue_number - round(issue_number)) > 0.001:
        return None
    if issue_number <= 0:
        return None
    return str(round(issue_number))


def _contains_issue_token(
    normalized_text: str,
    issue_token: str,
    *,
    allow_leading_zeroes: bool,
) -> bool:
    pattern = _issue_token_pattern(issue_token, allow_leading_zeroes=allow_leading_zeroes)
    return bool(pattern.search(normalized_text))


def _remove_issue_token(normalized_text: str, issue_token: str) -> str:
    pattern = _issue_token_pattern(issue_token, allow_leading_zeroes=False)
    return re.sub(r"\s+", " ", pattern.sub(" ", normalized_text)).strip()


def _issue_token_has_following_title_text(normalized_text: str, issue_token: str) -> bool:
    pattern = _issue_token_pattern(issue_token, allow_leading_zeroes=False)
    match = pattern.search(normalized_text)
    if match is None:
        return False
    trailing_tokens = normalized_text[match.end() :].split()
    return any(token and not token.isdigit() for token in trailing_tokens)


def _issue_token_pattern(issue_token: str, *, allow_leading_zeroes: bool) -> re.Pattern[str]:
    token = re.escape(issue_token)
    if allow_leading_zeroes:
        token = rf"0*{token}"
    return re.compile(rf"(?<!\w){token}(?!\w)", re.IGNORECASE)
