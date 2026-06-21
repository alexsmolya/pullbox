#!/usr/bin/env python3
"""Create or update a Pullbox GitHub Release from CircleCI."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

RELEASE_CATEGORY_HEADINGS = {
    "feat": "### ✨ Features",
    "fix": "### 🐛 Bug Fixes",
    "test": "### 🧪 Testing",
    "refactor": "### ♻️ Refactors",
    "docs": "### 📝 Docs",
    "chore": "### 🧰 Chores",
    "ci": "### 🏗️ CI / Build",
    "perf": "### ⚡ Performance",
    "style": "### 🎨 Style / UI Polish",
}
RELEASE_CATEGORY_ORDER = (
    "feat",
    "fix",
    "test",
    "refactor",
    "docs",
    "chore",
    "ci",
    "perf",
    "style",
    "other",
)
CONVENTIONAL_COMMIT_RE = re.compile(r"^(?P<prefix>[a-z]+)(?:\([^)]+\))?: (?P<message>.+)$")


def request_json(method: str, url: str, payload: dict[str, object] | None = None) -> object:
    token = os.environ["GITHUB_RELEASE_TOKEN"]
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def git_output(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def previous_git_tag(current_tag: str) -> str:
    try:
        tags = git_output("tag", "--sort=-creatordate", "--merged", "HEAD").splitlines()
        return next(
            (tag for tag in tags if tag != current_tag and tag.startswith("v")),
            "",
        )
    except Exception:
        return ""


def previous_published_release_tag(repository: str, current_tag: str) -> str:
    try:
        releases = request_json(
            "GET",
            f"https://api.github.com/repos/{repository}/releases?per_page=100",
        )
    except Exception:
        return ""
    if not isinstance(releases, list):
        return ""
    for release in releases:
        if not isinstance(release, dict):
            continue
        tag_name = release.get("tag_name")
        if isinstance(tag_name, str) and tag_name and tag_name != current_tag:
            return tag_name
    return ""


def full_changelog_url(repository: str, current_tag: str) -> str:
    previous = previous_published_release_tag(repository, current_tag)
    if not previous:
        previous = previous_git_tag(current_tag)
    if not previous:
        try:
            previous = git_output("rev-list", "--max-parents=0", "HEAD").splitlines()[0]
        except Exception:
            previous = "HEAD"
    return f"https://github.com/{repository}/compare/{previous}...{current_tag}"


def commit_details(current_tag: str) -> str:
    previous = previous_git_tag(current_tag)
    revision_range = f"{previous}..HEAD" if previous else "HEAD"
    try:
        subjects = git_output(
            "log", revision_range, "--pretty=format:%s", "--no-merges"
        ).splitlines()
    except Exception:
        subjects = []
    if not subjects:
        return ""
    grouped_notes: dict[str, list[str]] = {category: [] for category in RELEASE_CATEGORY_ORDER}
    for subject in subjects:
        category, note = release_note_for_subject(subject)
        grouped_notes[category].append(note)

    lines = ["## Commit Details", ""]
    for category in RELEASE_CATEGORY_ORDER:
        notes = grouped_notes[category]
        if not notes:
            continue
        lines.append(RELEASE_CATEGORY_HEADINGS.get(category, "### 🔧 Other Changes"))
        lines.append("")
        lines.extend(f"- {note}" for note in notes)
        lines.append("")
    return "\n".join(lines).rstrip()


def release_note_for_subject(subject: str) -> tuple[str, str]:
    match = CONVENTIONAL_COMMIT_RE.match(subject)
    if not match:
        return "other", subject
    prefix = match.group("prefix")
    if prefix not in RELEASE_CATEGORY_HEADINGS:
        return "other", subject
    return prefix, match.group("message")


def release_body(args: argparse.Namespace) -> str:
    changelog = Path(args.changelog).read_text(encoding="utf-8").strip()
    issuer = os.environ.get("COSIGN_CERTIFICATE_OIDC_ISSUER", "<circleci-oidc-issuer>")
    identity = os.environ.get("COSIGN_CERTIFICATE_IDENTITY", "<circleci-identity>")
    issuer_arg = shlex.quote(issuer)
    identity_arg = shlex.quote(identity)
    repository = args.repository
    sections = [
        f"""## What's Changed

{changelog}""",
        commit_details(args.tag),
        f"""## 🐳 Docker Images

```bash
docker pull ghcr.io/{repository}:{args.version}
docker pull docker.io/pullbox/pullbox:{args.version}
```

**Digest:** `{args.digest}`

## 🔐 Image Verification

Release images are signed with keyless Sigstore/Cosign using CircleCI OIDC.
These commands verify the exact multi-architecture image digest published by this release.

```bash
cosign verify \\
  --certificate-identity {identity_arg} \\
  --certificate-oidc-issuer {issuer_arg} \\
  ghcr.io/{repository}@{args.digest}

cosign verify \\
  --certificate-identity {identity_arg} \\
  --certificate-oidc-issuer {issuer_arg} \\
  docker.io/pullbox/pullbox@{args.digest}
```

**Full Changelog**: {full_changelog_url(repository, args.tag)}""",
    ]
    return "\n\n".join(section for section in sections if section).strip() + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--digest", required=True)
    parser.add_argument("--changelog", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    prerelease = args.version.startswith("0.") or "-" in args.version
    payload = {
        "tag_name": args.tag,
        "name": f"Pullbox {args.tag}",
        "body": release_body(args),
        "draft": False,
        "prerelease": prerelease,
    }
    releases_url = f"https://api.github.com/repos/{args.repository}/releases"
    try:
        request_json("POST", releases_url, payload)
        print(f"Created release {args.tag}")
    except urllib.error.HTTPError as exc:
        if exc.code != 422:
            raise
        existing = request_json("GET", f"{releases_url}/tags/{args.tag}")
        if not isinstance(existing, dict):
            raise ValueError(f"Existing release for {args.tag} was not an object") from exc
        release_id = existing["id"]
        request_json("PATCH", f"{releases_url}/{release_id}", payload)
        print(f"Updated release {args.tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
