"""Static SQL construction contracts for application code."""

from __future__ import annotations

import ast
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "pullbox"


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def test_application_sql_calls_do_not_use_f_strings() -> None:
    """Keep raw SQL construction literal/allowlisted, never interpolated inline."""
    offenders: list[str] = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            if _call_name(node) not in {"execute", "text"}:
                continue
            if isinstance(node.args[0], ast.JoinedStr):
                rel = path.relative_to(SRC_ROOT.parent)
                offenders.append(f"{rel}:{node.lineno}")

    assert offenders == []


def test_application_sqlalchemy_text_calls_use_string_literals() -> None:
    """Make every SQLAlchemy text() statement locally auditable."""
    offenders: list[str] = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            if _call_name(node) != "text":
                continue
            if isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                continue
            rel = path.relative_to(SRC_ROOT.parent)
            offenders.append(f"{rel}:{node.lineno}")

    assert offenders == []
