#!/usr/bin/env python3
"""Create or update a Pullbox GitHub Release from CircleCI."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import urllib.error
import urllib.request
from pathlib import Path


def request_json(
    method: str, url: str, payload: dict[str, object] | None = None
) -> dict[str, object]:
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


def commit_details(current_tag: str) -> str:
    try:
        previous_tag = git_output("tag", "--sort=-creatordate", "--merged", "HEAD").splitlines()
        previous = next(
            (tag for tag in previous_tag if tag != current_tag and tag.startswith("v")), ""
        )
    except Exception:
        previous = ""
    revision_range = f"{previous}..HEAD" if previous else "HEAD"
    try:
        subjects = git_output(
            "log", revision_range, "--pretty=format:%s", "--no-merges"
        ).splitlines()
    except Exception:
        subjects = []
    if not subjects:
        return ""
    lines = ["## Commit Details", ""]
    for subject in subjects:
        lines.append(f"- {subject}")
    return "\n".join(lines)


def release_body(args: argparse.Namespace) -> str:
    changelog = Path(args.changelog).read_text(encoding="utf-8").strip()
    issuer = os.environ.get("COSIGN_CERTIFICATE_OIDC_ISSUER", "<circleci-oidc-issuer>")
    identity = os.environ.get("COSIGN_CERTIFICATE_IDENTITY", "<circleci-identity>")
    issuer_arg = shlex.quote(issuer)
    identity_arg = shlex.quote(identity)
    repository = args.repository
    return f"""## What's Changed

{changelog}

{commit_details(args.tag)}

## Docker Images

```bash
docker pull ghcr.io/{repository}:{args.version}
docker pull docker.io/pullbox/pullbox:{args.version}
```

Digest: `{args.digest}`

## Image Verification

Release images are signed with keyless Sigstore/Cosign using CircleCI OIDC.

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
"""


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
        release_id = existing["id"]
        request_json("PATCH", f"{releases_url}/{release_id}", payload)
        print(f"Updated release {args.tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
