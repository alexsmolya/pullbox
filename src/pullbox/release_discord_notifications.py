"""Build safe Discord webhook payloads for completed Pullbox releases."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

_FINAL_VERSION = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)$"
)
_BULLET = re.compile(r"^\s*-\s+(?P<text>.+?)\s*$", re.MULTILINE)
_EMBED_COLOR = 0xF07A2C


def notification_channels(version: str) -> tuple[str, ...]:
    """Return public Discord channels appropriate for a final semantic release."""
    match = _FINAL_VERSION.fullmatch(version)
    if match is None:
        return ()
    if int(match.group("patch")) == 0:
        return ("changelog", "announcements")
    return ("changelog",)


def changelog_payload(version: str, changelog: str, release_url: str) -> dict[str, Any]:
    """Build the full, mention-safe changelog embed."""
    return _payload(
        title=f"Pullbox v{version} changelog",
        description=_truncate(changelog.strip(), 4096),
        release_url=release_url,
    )


def announcement_payload(version: str, changelog: str, release_url: str) -> dict[str, Any]:
    """Build the short announcement embed for major and minor releases."""
    highlights = [match.group("text") for match in _BULLET.finditer(changelog)][:2]
    description = "\n".join(f"• {highlight}" for highlight in highlights)
    if description:
        description += "\n\n"
    description += f"[Read the full release notes]({release_url})"
    return _payload(
        title=f"Pullbox v{version} is out",
        description=_truncate(description, 4096),
        release_url=release_url,
    )


def _payload(*, title: str, description: str, release_url: str) -> dict[str, Any]:
    return {
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": title,
                "description": description,
                "url": release_url,
                "color": _EMBED_COLOR,
                "footer": {"text": "Pullbox release"},
            }
        ],
    }


def _truncate(value: str, maximum: int) -> str:
    if len(value) <= maximum:
        return value
    return f"{value[: maximum - 1].rstrip()}…"


def main(argv: list[str] | None = None) -> int:
    """Write one validated Discord payload to standard output."""
    parser = argparse.ArgumentParser(description="Build a Pullbox Discord release payload.")
    parser.add_argument("--kind", choices=("announcement", "changelog"), required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--changelog", type=Path, required=True)
    parser.add_argument("--release-url", required=True)
    args = parser.parse_args(argv)

    changelog = args.changelog.read_text(encoding="utf-8")
    payload = (
        announcement_payload(args.version, changelog, args.release_url)
        if args.kind == "announcement"
        else changelog_payload(args.version, changelog, args.release_url)
    )
    json.dump(payload, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
