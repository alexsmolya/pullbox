"""Static contracts for the application logging security boundary."""

from __future__ import annotations

import ast
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src" / "pullbox"

_ALLOWED_STDLIB_LOGGING_IMPORTS = {
    SOURCE_ROOT / "logging.py",
    SOURCE_ROOT / "startup_log_tee.py",
    SOURCE_ROOT / "utilities" / "logging_config.py",
}


def test_stdlib_logging_imports_stay_in_logging_infrastructure_modules() -> None:
    offenders: list[str] = []

    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            uses_logging_import = (
                isinstance(node, ast.Import)
                and any(alias.name == "logging" for alias in node.names)
            ) or (
                isinstance(node, ast.ImportFrom)
                and (node.module == "logging" or node.module == "logging.handlers")
            )
            if uses_logging_import and path not in _ALLOWED_STDLIB_LOGGING_IMPORTS:
                relative_path = path.relative_to(SOURCE_ROOT.parent.parent).as_posix()
                offenders.append(f"{relative_path}:{node.lineno}")

    assert offenders == []


def test_structlog_processor_chain_sanitizes_after_exception_formatting() -> None:
    logging_module = (SOURCE_ROOT / "logging.py").read_text(encoding="utf-8")
    expected_order = "\n".join(
        [
            "structlog.processors.format_exc_info,",
            "        structlog.processors.UnicodeDecoder(),",
            "        sanitize_sensitive_data,",
        ]
    )

    assert expected_order in logging_module
