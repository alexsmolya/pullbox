#!/usr/bin/env python3
"""Decide whether Pullbox Docker validation should run in CircleCI."""

from __future__ import annotations

import os
import shlex
import subprocess
from fnmatch import fnmatch

DOCKER_PATHS = (
    "docker/**",
    "src/**",
    "alembic/**",
    "pyproject.toml",
    "package.json",
    "package-lock.json",
    ".grype.yaml",
    ".circleci/**",
    ".github/workflows/docker-release.yml",
    ".github/workflows/docker-validate.yml",
    ".github/workflows/release.yml",
    ".github/scripts/preflight-runner.sh",
)


def _env(name: str) -> str:
    return os.environ.get(name, "")


def _git(*args: str, check: bool = True) -> str:
    completed = subprocess.run(
        ["git", *args],
        text=True,
        capture_output=True,
        check=check,
    )
    return completed.stdout


def changed_files() -> list[str]:
    _git("fetch", "--no-tags", "origin", "develop:refs/remotes/origin/develop", check=False)
    base = _git("merge-base", "origin/develop", "HEAD", check=False).strip()
    diff_range = f"{base}..HEAD" if base else "HEAD~1..HEAD"
    return [
        line for line in _git("diff", "--name-only", diff_range, check=False).splitlines() if line
    ]


def docker_relevant(paths: list[str]) -> bool:
    return any(any(fnmatch(path, pattern) for pattern in DOCKER_PATHS) for path in paths)


def is_untrusted_pr() -> bool:
    if not _env("CIRCLE_PULL_REQUEST"):
        return False
    pr_username = _env("CIRCLE_PR_USERNAME") or _env("CIRCLE_PROJECT_USERNAME")
    pr_reponame = _env("CIRCLE_PR_REPONAME") or _env("CIRCLE_PROJECT_REPONAME")
    same_repo = pr_username == _env("CIRCLE_PROJECT_USERNAME") and pr_reponame == _env(
        "CIRCLE_PROJECT_REPONAME"
    )
    actor = _env("CIRCLE_USERNAME")
    return (
        not same_repo
        or actor == "dependabot[bot]"
        or _env("CIRCLE_BRANCH").startswith("dependabot/")
    )


def main() -> int:
    files = changed_files()
    required = docker_relevant(files)
    mode = "untrusted" if is_untrusted_pr() else "trusted"
    print(f"DOCKER_VALIDATE_REQUIRED={str(required).lower()}")
    print(f"DOCKER_VALIDATE_MODE={mode}")
    print(f"DOCKER_VALIDATE_CHANGED_FILES={shlex.quote(chr(10).join(files))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
