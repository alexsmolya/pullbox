#!/usr/bin/env python3
"""Summarize CodeQL alerts for the ref analyzed by a branch probe workflow."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable


API_VERSION = "2026-03-10"
DEFAULT_POLL_ATTEMPTS = 12
DEFAULT_POLL_SECONDS = 10


@dataclass(frozen=True)
class GitHubContext:
    api_url: str
    repository: str
    token: str
    ref: str
    sha: str


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _context() -> GitHubContext:
    token = _env("GITHUB_TOKEN") or _env("GH_TOKEN")
    repository = _env("GITHUB_REPOSITORY")
    ref = _env("PULLBOX_CODEQL_PROBE_REF") or _env("GITHUB_REF")
    sha = _env("PULLBOX_CODEQL_PROBE_SHA") or _env("GITHUB_SHA")
    missing = [
        name
        for name, value in {
            "GITHUB_TOKEN": token,
            "GITHUB_REPOSITORY": repository,
            "GITHUB_REF": ref,
            "GITHUB_SHA": sha,
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError(f"Missing required environment values: {', '.join(missing)}")
    return GitHubContext(
        api_url=_env("GITHUB_API_URL", "https://api.github.com").rstrip("/"),
        repository=repository,
        token=token,
        ref=ref,
        sha=sha,
    )


def _api_get(context: GitHubContext, path: str, params: dict[str, str]) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode(params)
    url = f"{context.api_url}{path}?{query}"
    items: list[dict[str, Any]] = []
    while url:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {context.token}",
                "X-GitHub-Api-Version": API_VERSION,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if isinstance(payload, list):
                    items.extend(item for item in payload if isinstance(item, dict))
                else:
                    raise RuntimeError(f"Expected list response from GitHub API: {path}")
                url = _next_link(response.headers.get("Link", ""))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GitHub API request failed: {exc.code} {body}") from exc
    return items


def _next_link(link_header: str) -> str:
    for part in link_header.split(","):
        url_part, _, rel_part = part.partition(";")
        if 'rel="next"' not in rel_part:
            continue
        return url_part.strip().removeprefix("<").removesuffix(">")
    return ""


def _latest_analysis(context: GitHubContext) -> dict[str, Any] | None:
    owner, repo = context.repository.split("/", maxsplit=1)
    path = f"/repos/{owner}/{repo}/code-scanning/analyses"
    analyses = _api_get(context, path, {"per_page": "100", "tool_name": "CodeQL"})
    matches = [
        analysis
        for analysis in analyses
        if analysis.get("ref") == context.ref and analysis.get("commit_sha") == context.sha
    ]
    if not matches:
        return None
    return sorted(matches, key=lambda item: item.get("created_at", ""), reverse=True)[0]


def _alerts_for_state(context: GitHubContext, state: str) -> list[dict[str, Any]]:
    owner, repo = context.repository.split("/", maxsplit=1)
    path = f"/repos/{owner}/{repo}/code-scanning/alerts"
    return _api_get(
        context,
        path,
        {
            "state": state,
            "per_page": "100",
            "tool_name": "CodeQL",
            "ref": context.ref,
        },
    )


def _poll_latest_analysis(context: GitHubContext) -> dict[str, Any] | None:
    attempts = int(_env("PULLBOX_CODEQL_SUMMARY_POLL_ATTEMPTS", str(DEFAULT_POLL_ATTEMPTS)))
    wait_seconds = int(_env("PULLBOX_CODEQL_SUMMARY_POLL_SECONDS", str(DEFAULT_POLL_SECONDS)))
    for attempt in range(1, attempts + 1):
        analysis = _latest_analysis(context)
        if analysis is not None:
            return analysis
        if attempt < attempts:
            print(
                f"CodeQL analysis for {context.ref}@{context.sha[:12]} is not indexed yet; "
                f"waiting {wait_seconds}s..."
            )
            time.sleep(wait_seconds)
    return None


def _rule_rows(alerts: Iterable[dict[str, Any]]) -> list[tuple[str, str, int]]:
    counts: Counter[tuple[str, str]] = Counter()
    for alert in alerts:
        rule = alert.get("rule") if isinstance(alert.get("rule"), dict) else {}
        rule_id = str(rule.get("id") or "unknown")
        name = str(rule.get("name") or rule_id)
        counts[(rule_id, name)] += 1
    return [(rule_id, name, count) for (rule_id, name), count in counts.most_common()]


def _markdown_table(rows: list[tuple[str, str, int]]) -> str:
    if not rows:
        return "_None._"
    lines = ["| Rule | Name | Count |", "| --- | --- | ---: |"]
    for rule_id, name, count in rows:
        lines.append(f"| `{rule_id}` | {name} | {count} |")
    return "\n".join(lines)


def _append_step_summary(markdown: str) -> None:
    summary_path = _env("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    with open(summary_path, "a", encoding="utf-8") as summary:
        summary.write(markdown)
        summary.write("\n")


def main() -> int:
    context = _context()
    analysis = _poll_latest_analysis(context)
    open_alerts = _alerts_for_state(context, "open")
    dismissed_alerts = _alerts_for_state(context, "dismissed")
    fixed_alerts = _alerts_for_state(context, "fixed")

    lines = [
        "## CodeQL Branch Probe",
        "",
        f"- Ref: `{context.ref}`",
        f"- Commit: `{context.sha}`",
    ]
    if analysis:
        lines.extend(
            [
                f"- Analysis ID: `{analysis.get('id')}`",
                f"- Rules evaluated: `{analysis.get('rules_count', 'unknown')}`",
                f"- Raw results: `{analysis.get('results_count', 'unknown')}`",
            ]
        )
    else:
        lines.append("- Analysis: not visible through the API before polling ended")

    lines.extend(
        [
            f"- Open alerts: `{len(open_alerts)}`",
            f"- Dismissed/triaged alerts: `{len(dismissed_alerts)}`",
            f"- Fixed alerts on this ref: `{len(fixed_alerts)}`",
            "",
            "### Open Alerts By Rule",
            _markdown_table(_rule_rows(open_alerts)),
            "",
            "### Dismissed/Triaged Alerts By Rule",
            _markdown_table(_rule_rows(dismissed_alerts)),
        ]
    )
    output = "\n".join(lines)
    print(output)
    _append_step_summary(output)

    fail_on_open = _env("PULLBOX_CODEQL_BRANCH_PROBE_FAIL_ON_OPEN").lower() == "true"
    if fail_on_open and open_alerts:
        print(
            f"::error::CodeQL branch probe found {len(open_alerts)} open alert(s) "
            f"for {context.ref}."
        )
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"::warning::Unable to summarize CodeQL branch alerts: {exc}", file=sys.stderr)
        raise
