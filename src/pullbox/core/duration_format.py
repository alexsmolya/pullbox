"""Helpers for consistent UI-friendly duration labels."""

from __future__ import annotations

import re

_MS_TOKEN_RE = re.compile(r"(\d+(?:\.\d+)?)\s*ms\b")


def format_duration_ms(value: int | float) -> str:
    """Format millisecond values for compact UI display."""
    duration_ms = float(value)
    if duration_ms < 1:
        return "<1ms"
    if duration_ms < 1000:
        return f"{round(duration_ms):.0f}ms"
    return f"{duration_ms / 1000:.1f}s"


def format_duration_ms_label(value: object, *, fallback: str = "—") -> str:
    """Format a maybe-numeric millisecond value or return a fallback label."""
    if not isinstance(value, int | float):
        return fallback
    return format_duration_ms(float(value))


def replace_duration_ms_tokens(text: str) -> str:
    """Rewrite embedded millisecond tokens with compact display labels."""

    def _replace(match: re.Match[str]) -> str:
        return format_duration_ms(float(match.group(1)))

    return _MS_TOKEN_RE.sub(_replace, text)
