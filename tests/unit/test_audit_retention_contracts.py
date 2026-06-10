"""Static contracts for security audit-log retention."""

from __future__ import annotations

from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "pullbox"


def test_regular_cleanup_code_does_not_delete_audit_logs() -> None:
    """Audit logs must not be pruned by ordinary cleanup/retention tasks."""
    forbidden_patterns = (
        "delete(AuditLog",
        "sa_delete(AuditLog",
        ".delete(AuditLog",
        "DELETE FROM audit_logs",
        "delete(audit_logs",
        "DELETE audit_logs",
    )

    offenders: list[str] = []
    for path in SRC_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for pattern in forbidden_patterns:
            if pattern in text:
                offenders.append(f"{path.relative_to(SRC_ROOT)} contains {pattern!r}")

    assert offenders == []
