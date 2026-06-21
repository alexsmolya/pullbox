"""Contracts for the CircleCI GitHub Release helper."""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
GITHUB_RELEASE_SCRIPT = REPO_ROOT / ".circleci" / "scripts" / "github_release.py"


def _load_github_release_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "circleci_github_release",
        GITHUB_RELEASE_SCRIPT,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_body_keeps_public_release_note_format(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_github_release_module()
    changelog = tmp_path / "curated.md"
    changelog.write_text("Curated release notes.", encoding="utf-8")

    def fake_git_output(*args: str) -> str:
        if args == ("tag", "--sort=-creatordate", "--merged", "HEAD"):
            return "v0.9.11-rc3\nv0.9.11-rc2\nv0.9.11-rc1\nv0.9.10"
        if args == ("log", "v0.9.11-rc2..HEAD", "--pretty=format:%s", "--no-merges"):
            return "\n".join(
                [
                    "ci: use sigstore audience token for release signing",
                    "fix(ui): repair task status pills",
                    "release note without prefix",
                ]
            )
        raise AssertionError(f"unexpected git command: {args!r}")

    def fake_request_json(
        method: str,
        url: str,
        payload: dict[str, object] | None = None,
    ) -> list[dict[str, object]]:
        assert method == "GET"
        assert url == "https://api.github.com/repos/pullboxapp/pullbox/releases?per_page=100"
        assert payload is None
        return [
            {"tag_name": "v0.9.11-rc3"},
            {"tag_name": "v0.9.12", "draft": True},
            {"tag_name": "v0.9.10"},
        ]

    monkeypatch.setattr(module, "git_output", fake_git_output)
    monkeypatch.setattr(module, "request_json", fake_request_json)
    monkeypatch.setenv(
        "COSIGN_CERTIFICATE_IDENTITY",
        "https://circleci.com/api/v2/projects/example/pipeline-definitions/example",
    )
    monkeypatch.setenv(
        "COSIGN_CERTIFICATE_OIDC_ISSUER",
        "https://oidc.circleci.com/org/example",
    )

    body = module.release_body(
        argparse.Namespace(
            repository="pullboxapp/pullbox",
            tag="v0.9.11-rc3",
            version="0.9.11-rc3",
            digest="sha256:" + "a" * 64,
            changelog=str(changelog),
        )
    )

    assert "Curated release notes." in body
    assert "## Commit Details" in body
    assert "### 🏗️ CI / Build" in body
    assert "- use sigstore audience token for release signing" in body
    assert "### 🐛 Bug Fixes" in body
    assert "- repair task status pills" in body
    assert "### 🔧 Other Changes" in body
    assert "- release note without prefix" in body
    assert "## 🐳 Docker Images" in body
    assert "**Digest:** `sha256:" in body
    assert "## 🔐 Image Verification" in body
    assert "These commands verify the exact multi-architecture image digest" in body
    assert (
        "**Full Changelog**: https://github.com/pullboxapp/pullbox/compare/v0.9.10...v0.9.11-rc3"
    ) in body
