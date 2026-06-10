"""Static outbound HTTP client security contracts."""

from __future__ import annotations

import ast
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src" / "pullbox"


def _is_httpx_async_client_call(node: ast.Call) -> bool:
    return (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "AsyncClient"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in {"httpx", "_httpx"}
    )


def test_application_httpx_async_clients_have_explicit_timeout() -> None:
    missing_timeout: list[str] = []

    for path in SOURCE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not _is_httpx_async_client_call(node):
                continue
            if not any(keyword.arg == "timeout" for keyword in node.keywords):
                relative_path = path.relative_to(SOURCE_ROOT.parent.parent).as_posix()
                missing_timeout.append(f"{relative_path}:{node.lineno}")

    assert missing_timeout == []


def test_application_code_does_not_use_requests_library() -> None:
    offenders: list[str] = []

    for path in SOURCE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(alias.name == "requests" for alias in node.names):
                    relative_path = path.relative_to(SOURCE_ROOT.parent.parent).as_posix()
                    offenders.append(f"{relative_path}:{node.lineno}")
            elif isinstance(node, ast.ImportFrom) and node.module == "requests":
                relative_path = path.relative_to(SOURCE_ROOT.parent.parent).as_posix()
                offenders.append(f"{relative_path}:{node.lineno}")

    assert offenders == []


def test_application_code_does_not_disable_httpx_tls_verification() -> None:
    offenders: list[str] = []

    for path in SOURCE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if (
                    keyword.arg == "verify"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is False
                ):
                    relative_path = path.relative_to(SOURCE_ROOT.parent.parent).as_posix()
                    offenders.append(f"{relative_path}:{node.lineno}")

    assert offenders == []
