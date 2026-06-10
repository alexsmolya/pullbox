"""Architectural guardrails for database session ownership."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src" / "pullbox"
REQUEST_ROUTE_PATHS = (
    SRC_ROOT / "api" / "v1",
    SRC_ROOT / "ui",
    SRC_ROOT / "utilities" / "router.py",
)


def _python_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(path.rglob("*.py"))


def test_runtime_code_does_not_import_sync_sqlalchemy_session() -> None:
    """Runtime database access should stay on AsyncSession."""
    offenders: list[str] = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        text = path.read_text()
        if "from sqlalchemy.orm import Session" in text:
            offenders.append(str(path.relative_to(PROJECT_ROOT)))

    assert offenders == []


def test_request_route_modules_do_not_create_ad_hoc_sessions() -> None:
    """Request routes should use the shared DbSession dependency."""
    forbidden_tokens = (
        "get_session_factory(",
        "async_sessionmaker(",
        "create_async_engine(",
    )
    offenders: list[str] = []
    for root in REQUEST_ROUTE_PATHS:
        for path in _python_files(root):
            text = path.read_text()
            if any(token in text for token in forbidden_tokens):
                offenders.append(str(path.relative_to(PROJECT_ROOT)))

    assert offenders == []


def test_relationship_level_joined_defaults_are_reviewed_exceptions() -> None:
    """Joined relationship defaults should stay narrow and intentional."""
    allowed_files = {
        SRC_ROOT / "models" / "pending_match.py",
    }
    offenders: list[str] = []
    for path in sorted((SRC_ROOT / "models").rglob("*.py")):
        if path in allowed_files:
            continue
        text = path.read_text()
        if 'lazy="joined"' in text or "lazy='joined'" in text:
            offenders.append(str(path.relative_to(PROJECT_ROOT)))

    assert offenders == []
