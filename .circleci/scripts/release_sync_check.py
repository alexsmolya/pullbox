#!/usr/bin/env python3
"""Detect Pullbox release-sync PRs that may skip heavyweight CircleCI jobs.

The logic mirrors the existing GitHub Actions validator:

- PR base must be develop.
- Head branch must start with feature/sync-develop-.
- PR must be same-repository and not Dependabot.
- origin/main must contain origin/develop.
- PR head must contain origin/main.
- The only change after origin/main must be src/pullbox/__init__.py.
- Version must move from X.Y.Z to X.Y.(Z+1)-dev.

Output is a shell env file consumed by later CircleCI jobs.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path

VERSION_FILE = "src/pullbox/__init__.py"
ALLOWED_SYNC_CHANGES = {VERSION_FILE}
SYNC_BRANCH_PREFIX = "feature/sync-develop-"
VERSION_RE = re.compile(r'^__version__ = "([^"]+)"$', re.MULTILINE)
RELEASE_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


@dataclass(frozen=True)
class ValidationResult:
    is_sync: bool
    reason: str


def _env(name: str) -> str:
    return os.environ.get(name, "")


def _run_git(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        text=True,
        capture_output=True,
    )


def _git_succeeds(*args: str, cwd: Path) -> bool:
    return _run_git(*args, cwd=cwd, check=False).returncode == 0


def _git_stdout(*args: str, cwd: Path) -> str:
    return _run_git(*args, cwd=cwd).stdout


def _fetch_refs(cwd: Path) -> None:
    _run_git(
        "fetch",
        "--no-tags",
        "origin",
        "main:refs/remotes/origin/main",
        "develop:refs/remotes/origin/develop",
        cwd=cwd,
        check=False,
    )


def _github_api_json(url: str) -> dict[str, object] | None:
    token = _env("GITHUB_TOKEN") or _env("GH_TOKEN") or _env("GITHUB_RELEASE_TOKEN")
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def _pull_request_base_branch(repository: str) -> str:
    for key in ("CIRCLE_PR_BASE_BRANCH", "GITHUB_BASE_REF", "PULLBOX_BASE_BRANCH"):
        if _env(key):
            return _env(key)

    pull_request_url = _env("CIRCLE_PULL_REQUEST")
    if not pull_request_url or not repository:
        return ""

    pr_number = pull_request_url.rstrip("/").split("/")[-1]
    if not pr_number.isdigit():
        return ""

    data = _github_api_json(f"https://api.github.com/repos/{repository}/pulls/{pr_number}")
    if not data:
        return ""
    base = data.get("base")
    if isinstance(base, dict):
        ref = base.get("ref")
        if isinstance(ref, str):
            return ref
    return ""


def extract_version(text: str) -> str | None:
    match = VERSION_RE.search(text)
    return match.group(1) if match else None


def expected_next_dev_version(released_version: str) -> str | None:
    match = RELEASE_VERSION_RE.fullmatch(released_version)
    if not match:
        return None
    major, minor, patch = (int(part) for part in match.groups())
    return f"{major}.{minor}.{patch + 1}-dev"


def replace_version_line(text: str, version: str) -> str:
    return VERSION_RE.sub(f'__version__ = "{version}"', text, count=1)


def version_bump_is_release_sync(main_text: str, head_text: str) -> ValidationResult:
    main_version = extract_version(main_text)
    head_version = extract_version(head_text)
    if main_version is None or head_version is None:
        return ValidationResult(False, "could not read Pullbox version")

    expected = expected_next_dev_version(main_version)
    if expected is None:
        return ValidationResult(False, f"main version is not a final release: {main_version}")
    if head_version != expected:
        return ValidationResult(
            False,
            f"expected {VERSION_FILE} to be bumped from {main_version} to {expected}; "
            f"found {head_version}",
        )
    expected_head_text = replace_version_line(main_text, expected)
    if head_text != expected_head_text:
        return ValidationResult(
            False,
            f"{VERSION_FILE} contains changes beyond the expected version bump",
        )
    return ValidationResult(True, f"release sync with dev bump {main_version} -> {head_version}")


def validate(cwd: Path) -> ValidationResult:
    pull_request_url = _env("CIRCLE_PULL_REQUEST")
    if not pull_request_url:
        return ValidationResult(False, "not a pull request")

    repository = f"{_env('CIRCLE_PROJECT_USERNAME')}/{_env('CIRCLE_PROJECT_REPONAME')}".strip("/")
    base_branch = _pull_request_base_branch(repository)
    if base_branch != "develop":
        return ValidationResult(False, f"base branch is not develop: {base_branch or '<unknown>'}")

    head_ref = _env("CIRCLE_BRANCH")
    if not head_ref.startswith(SYNC_BRANCH_PREFIX):
        return ValidationResult(False, f"head branch does not start with {SYNC_BRANCH_PREFIX}")

    pr_username = _env("CIRCLE_PR_USERNAME") or _env("CIRCLE_PROJECT_USERNAME")
    pr_reponame = _env("CIRCLE_PR_REPONAME") or _env("CIRCLE_PROJECT_REPONAME")
    head_repository = f"{pr_username}/{pr_reponame}".strip("/")
    actor = _env("CIRCLE_USERNAME")
    if head_repository != repository:
        return ValidationResult(False, "fork pull requests cannot use the sync fast path")
    if actor == "dependabot[bot]" or head_ref.startswith("dependabot/"):
        return ValidationResult(False, "Dependabot pull requests cannot use the sync fast path")

    try:
        _fetch_refs(cwd)
        if not _git_succeeds(
            "merge-base", "--is-ancestor", "origin/develop", "origin/main", cwd=cwd
        ):
            return ValidationResult(False, "origin/main is not a descendant of origin/develop")
        if not _git_succeeds("merge-base", "--is-ancestor", "origin/main", "HEAD", cwd=cwd):
            return ValidationResult(False, "pull request head does not include origin/main")

        changed = set(
            filter(
                None,
                _git_stdout("diff", "--name-only", "origin/main..HEAD", cwd=cwd).splitlines(),
            )
        )
        if changed != ALLOWED_SYNC_CHANGES:
            return ValidationResult(
                False,
                "release sync fast path only allows "
                f"{sorted(ALLOWED_SYNC_CHANGES)} after origin/main; found {sorted(changed)}",
            )

        main_text = _git_stdout("show", f"origin/main:{VERSION_FILE}", cwd=cwd)
        head_text = (cwd / VERSION_FILE).read_text(encoding="utf-8")
        return version_bump_is_release_sync(main_text, head_text)
    except Exception as exc:
        return ValidationResult(False, f"could not validate release sync PR: {exc}")


def main() -> int:
    result = validate(Path.cwd())
    print(f"RELEASE_SYNC={str(result.is_sync).lower()}")
    print(f"RELEASE_SYNC_REASON={shlex.quote(result.reason)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
