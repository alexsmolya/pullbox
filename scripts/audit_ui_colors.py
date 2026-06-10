#!/usr/bin/env python3
"""Audit UI color usage outside the standardized Pullbox design tokens."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]

TARGET_GLOBS = (
    "src/pullbox/ui/templates/**/*.html",
    "src/pullbox/ui/static/css/input.css",
    "src/pullbox/ui/static/js/pullbox.js",
)

TOKEN_BASES = {
    "pb-brand",
    "pb-brand-hover",
    "pb-brand-dim",
    "pb-brand-border",
    "pb-brand-signal",
    "pb-brand-signal-dim",
    "pb-brand-signal-hover",
    "pb-brand-signal-border",
    "pb-interactive",
    "pb-interactive-hover",
    "pb-interactive-dim",
    "pb-interactive-border",
    "pb-success",
    "pb-success-dim",
    "pb-warning",
    "pb-warning-dim",
    "pb-error",
    "pb-error-dim",
    "pb-info",
    "pb-info-dim",
    "pb-purple",
    "pb-purple-dim",
    "pb-base",
    "pb-surface",
    "pb-card",
    "pb-card-hover",
    "pb-input",
    "pb-overlay",
    "pb-text",
    "pb-text-sec",
    "pb-text-dim",
    "pb-border",
    "pb-border-hover",
    "pb-border-strong",
}

ALLOWED_NEUTRALS = {
    "white",
    "black",
    "transparent",
    "current",
    "inherit",
}

LEGACY_ALIASES = {
    "surface",
    "pb",
}

PALETTE_FAMILIES = {
    "slate",
    "gray",
    "zinc",
    "neutral",
    "stone",
    "red",
    "orange",
    "amber",
    "yellow",
    "lime",
    "green",
    "emerald",
    "teal",
    "cyan",
    "sky",
    "blue",
    "indigo",
    "violet",
    "purple",
    "fuchsia",
    "pink",
    "rose",
}

UTILITY_RE = re.compile(
    r"(?<![\w-])(?P<full>(?:!?[\w\-\[\]\/%.#]+:)*(?P<base>"
    r"(?:bg|text|border|divide|ring|placeholder|from|via|to|stroke|fill|accent)-"
    r"(?:pb-[\w-]+|surface(?:-\d+)?|pb-\d+|(?:"
    + "|".join(sorted(PALETTE_FAMILIES))
    + r")(?:-\d+)?(?:/\[[^\]]+\]|/\d+)?|\[#[0-9A-Fa-f]{3,8}\](?:/\d+)?|white(?:/\d+)?|black(?:/\d+)?|transparent|current|inherit)))"
)

HEX_RE = re.compile(r"#[0-9A-Fa-f]{3,8}")
COLOR_FUNC_RE = re.compile(r"\b(?:rgb|rgba|hsl|hsla)\([^)]*\)")
INLINE_STYLE_RE = re.compile(
    r'style\s*=\s*"[^"]*(?:color|background-color|border-color|fill|stroke)\s*:\s*([^;"\']+)'
)


@dataclass(frozen=True)
class Finding:
    category: str
    token: str
    file: str
    line_no: int
    line: str


def iter_target_files() -> list[Path]:
    files: list[Path] = []
    for pattern in TARGET_GLOBS:
        files.extend(ROOT.glob(pattern))
    return sorted(set(files))


def normalize_color_base(base: str) -> str:
    if "/" in base:
        base = base.split("/", 1)[0]
    return base


def classify_utility(base: str) -> str | None:
    _, value = base.split("-", 1)
    normalized = normalize_color_base(value)
    if normalized in ALLOWED_NEUTRALS:
        return None
    if normalized in TOKEN_BASES:
        return None
    family = normalized.split("-", 1)[0]
    if family in LEGACY_ALIASES:
        return "legacy_alias"
    if normalized.startswith("[#"):
        return "arbitrary_hex_utility"
    if family in PALETTE_FAMILIES:
        return "hard_coded_palette"
    return "other_color_utility"


def line_is_token_definition(path: Path, line: str) -> bool:
    return path.name == "input.css" and "--pb-" in line


def collect_findings() -> list[Finding]:
    findings: list[Finding] = []
    for path in iter_target_files():
        relative = path.relative_to(ROOT).as_posix()
        for line_no, raw_line in enumerate(path.read_text().splitlines(), start=1):
            line = raw_line.strip()

            for match in UTILITY_RE.finditer(raw_line):
                base = match.group("base")
                category = classify_utility(base)
                if category is None:
                    continue
                findings.append(
                    Finding(
                        category=category,
                        token=base,
                        file=relative,
                        line_no=line_no,
                        line=line,
                    )
                )

            if not line_is_token_definition(path, raw_line):
                for token in HEX_RE.findall(raw_line):
                    findings.append(
                        Finding(
                            category="direct_hex_literal",
                            token=token,
                            file=relative,
                            line_no=line_no,
                            line=line,
                        )
                    )

                for token in COLOR_FUNC_RE.findall(raw_line):
                    findings.append(
                        Finding(
                            category="direct_color_function",
                            token=token,
                            file=relative,
                            line_no=line_no,
                            line=line,
                        )
                    )

            for match in INLINE_STYLE_RE.finditer(raw_line):
                value = match.group(1).strip()
                if "var(--pb-" in value:
                    continue
                findings.append(
                    Finding(
                        category="inline_style_color",
                        token=value,
                        file=relative,
                        line_no=line_no,
                        line=line,
                    )
                )

    return findings


def print_section(title: str) -> None:
    print(f"\n{title}")
    print("-" * len(title))


def main() -> None:
    findings = collect_findings()
    category_counts = Counter(f.category for f in findings)
    file_counts = Counter(f.file for f in findings)

    by_category: dict[str, list[Finding]] = defaultdict(list)
    for finding in findings:
        by_category[finding.category].append(finding)

    print("UI Color Audit")
    print("==============")
    print(f"Scanned {len(iter_target_files())} files")
    print(f"Found {len(findings)} non-token color findings")

    print_section("Category Summary")
    for category, count in sorted(category_counts.items(), key=lambda item: (-item[1], item[0])):
        print(f"{category}: {count}")

    print_section("Top Files")
    for file, count in file_counts.most_common(20):
        print(f"{count:>3}  {file}")

    for category in (
        "hard_coded_palette",
        "legacy_alias",
        "arbitrary_hex_utility",
        "direct_hex_literal",
        "direct_color_function",
        "inline_style_color",
        "other_color_utility",
    ):
        items = by_category.get(category)
        if not items:
            continue
        token_counts = Counter(f.token for f in items)
        print_section(f"{category} Tokens")
        for token, count in token_counts.most_common(25):
            sample = next(f for f in items if f.token == token)
            print(
                f"{count:>3}  {token:<28} {sample.file}:{sample.line_no}"
            )

    print_section("High-Signal Samples")
    seen: set[tuple[str, str]] = set()
    for finding in findings:
        key = (finding.category, finding.token)
        if key in seen:
            continue
        seen.add(key)
        print(f"[{finding.category}] {finding.file}:{finding.line_no}")
        print(f"  token: {finding.token}")
        print(f"  line:  {finding.line}")
        if len(seen) >= 20:
            break


if __name__ == "__main__":
    main()
