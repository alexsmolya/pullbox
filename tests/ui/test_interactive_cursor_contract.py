"""Static contracts for consistent cursor affordances on interactive controls."""

from __future__ import annotations

import re
from pathlib import Path

INPUT_CSS = Path("src/pullbox/ui/static/css/input.css")


def _css() -> str:
    return INPUT_CSS.read_text(encoding="utf-8")


def _cursor_contract(css: str, cursor: str) -> str:
    match = re.search(
        rf"/\* Interactive cursor contract: {cursor} \*/\s*"
        rf":where\((?P<selectors>.*?)\)\s*\{{\s*cursor: {re.escape(cursor)};",
        css,
        re.DOTALL,
    )
    assert match is not None, f"Missing {cursor} cursor contract"
    return match.group("selectors")


def test_enabled_interactive_controls_use_pointer_cursor() -> None:
    selectors = _cursor_contract(_css(), "pointer")

    for selector in (
        'a[href]:not([aria-disabled="true"])',
        'button:not(:disabled):not([aria-disabled="true"])',
        'input[type="button"]:not(:disabled)',
        'input[type="submit"]:not(:disabled)',
        'input[type="reset"]:not(:disabled)',
        "select:not(:disabled)",
        "summary",
        '[role="button"]:not([aria-disabled="true"])',
        '[role="link"]:not([aria-disabled="true"])',
        "label:has(",
    ):
        assert selector in selectors


def test_disabled_interactive_controls_use_not_allowed_cursor() -> None:
    selectors = _cursor_contract(_css(), "not-allowed")

    for selector in (
        "button:disabled",
        "input:disabled",
        "select:disabled",
        '[aria-disabled="true"]',
    ):
        assert selector in selectors


def test_cursor_contract_does_not_treat_background_event_handlers_as_controls() -> None:
    selectors = _cursor_contract(_css(), "pointer")

    assert "hx-get" not in selectors
    assert "@click" not in selectors
    assert "x-on:click" not in selectors
