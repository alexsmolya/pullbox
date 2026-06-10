"""Tests for build metadata resolution."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pullbox.core import build_metadata

if TYPE_CHECKING:
    from pathlib import Path


def test_build_metadata_prefers_explicit_env(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("PULLBOX_BUILD_DATE", "2026-05-12T13:04:05Z")
    monkeypatch.setenv("PULLBOX_GIT_BRANCH", "feature/ui-followups")
    monkeypatch.setenv("PULLBOX_GIT_SHA", "abcdef1234567890")

    metadata = build_metadata.get_build_metadata()

    assert metadata.release_date == "2026-05-12"
    assert metadata.branch == "feature/ui-followups"
    assert metadata.commit == "abcdef1"


def test_build_metadata_falls_back_to_checkout_files(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    repo_root = tmp_path / "repo"
    git_dir = repo_root / ".git"
    branch_name = "feature/ui-followups"
    ref_path = git_dir / "refs" / "heads" / "feature" / "ui-followups"
    log_path = git_dir / "logs" / "refs" / "heads" / "feature" / "ui-followups"
    repo_root.mkdir()
    ref_path.parent.mkdir(parents=True)
    log_path.parent.mkdir(parents=True)

    full_sha = "1234567890abcdef1234567890abcdef12345678"
    (git_dir / "HEAD").write_text(f"ref: refs/heads/{branch_name}\n", encoding="utf-8")
    ref_path.write_text(f"{full_sha}\n", encoding="utf-8")
    log_path.write_text(
        (
            "0000000000000000000000000000000000000000 "
            f"{full_sha} Test User <test@example.com> 1715558400 -0700\tcommit: test\n"
        ),
        encoding="utf-8",
    )

    monkeypatch.delenv("PULLBOX_BUILD_DATE", raising=False)
    monkeypatch.delenv("PULLBOX_GIT_BRANCH", raising=False)
    monkeypatch.delenv("PULLBOX_GIT_SHA", raising=False)
    monkeypatch.setattr(build_metadata, "_repo_root", lambda: repo_root)
    monkeypatch.setattr(build_metadata, "_git_output", lambda *_args: None)

    metadata = build_metadata.get_build_metadata()

    assert metadata.release_date == "2024-05-13"
    assert metadata.branch == branch_name
    assert metadata.commit == "1234567"
