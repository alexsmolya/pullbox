"""Architectural guardrails for persisted/runtime datetime conventions."""

from __future__ import annotations

import re
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src" / "pullbox"
BARE_DATETIME_NOW_PATTERN = re.compile(r"\bdatetime\.now\(\)")


def test_runtime_code_does_not_use_bare_local_datetime_now() -> None:
    """Runtime timestamps should be explicit UTC or an intentional display timezone."""
    offenders: list[str] = []
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        text = path.read_text()
        if BARE_DATETIME_NOW_PATTERN.search(text):
            offenders.append(str(path.relative_to(SOURCE_ROOT)))

    assert offenders == []
