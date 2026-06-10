#!/usr/bin/env python3
"""Audit Pullbox semantic color tokens against WCAG 2.2 AA thresholds."""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CSS_PATH = ROOT / "src" / "pullbox" / "ui" / "static" / "css" / "input.css"

TOKEN_PATTERN = re.compile(r"--(?P<name>[a-z0-9-]+)\s*:\s*(?P<value>[^;]+);")
HEX_PATTERN = re.compile(r"^#([0-9a-fA-F]{6})$")
RGBA_PATTERN = re.compile(
    r"^rgba\(\s*(?P<r>\d{1,3})\s*,\s*(?P<g>\d{1,3})\s*,\s*(?P<b>\d{1,3})\s*,\s*(?P<a>0?\.\d+|1(?:\.0+)?)\s*\)$"
)


@dataclass(frozen=True)
class ContrastCheck:
    foreground: str
    background: str
    minimum: float
    label: str


TEXT_CHECKS = [
    ContrastCheck("pb-text-primary", "pb-surface-app", 4.5, "primary text on app"),
    ContrastCheck("pb-text-primary", "pb-surface-shell", 4.5, "primary text on shell"),
    ContrastCheck("pb-text-primary", "pb-surface-card", 4.5, "primary text on card"),
    ContrastCheck("pb-text-primary", "pb-surface-input", 4.5, "primary text on input"),
    ContrastCheck("pb-text-secondary", "pb-surface-app", 4.5, "secondary text on app"),
    ContrastCheck("pb-text-secondary", "pb-surface-shell", 4.5, "secondary text on shell"),
    ContrastCheck("pb-text-secondary", "pb-surface-card", 4.5, "secondary text on card"),
    ContrastCheck("pb-text-secondary", "pb-surface-input", 4.5, "secondary text on input"),
    ContrastCheck("pb-text-tertiary", "pb-surface-app", 4.5, "tertiary text on app"),
    ContrastCheck("pb-text-tertiary", "pb-surface-shell", 4.5, "tertiary text on shell"),
    ContrastCheck("pb-text-tertiary", "pb-surface-card", 4.5, "tertiary text on card"),
    ContrastCheck("pb-text-tertiary", "pb-surface-input", 4.5, "tertiary text on input"),
    ContrastCheck("pb-interactive", "pb-surface-app", 4.5, "interactive text on app"),
    ContrastCheck("pb-interactive", "pb-surface-shell", 4.5, "interactive text on shell"),
    ContrastCheck("pb-interactive", "pb-surface-card", 4.5, "interactive text on card"),
    ContrastCheck("pb-interactive", "pb-surface-input", 4.5, "interactive text on input"),
    ContrastCheck("pb-brand", "pb-surface-app", 4.5, "brand text on app"),
    ContrastCheck("pb-brand", "pb-surface-shell", 4.5, "brand text on shell"),
    ContrastCheck("pb-brand", "pb-surface-card", 4.5, "brand text on card"),
    ContrastCheck("pb-brand", "pb-surface-input", 4.5, "brand text on input"),
    ContrastCheck("pb-status-success", "pb-surface-card", 4.5, "success text on card"),
    ContrastCheck("pb-status-warning", "pb-surface-card", 4.5, "warning text on card"),
    ContrastCheck("pb-status-danger", "pb-surface-card", 4.5, "danger text on card"),
    ContrastCheck("pb-status-info", "pb-surface-card", 4.5, "info text on card"),
]

CONTROL_CHECKS = [
    ContrastCheck("pb-text-inverse", "pb-interactive", 4.5, "inverse text on interactive"),
    ContrastCheck("pb-text-inverse", "pb-interactive-hover", 4.5, "inverse text on interactive hover"),
    ContrastCheck("pb-text-inverse", "pb-brand", 4.5, "inverse text on brand"),
    ContrastCheck("pb-text-inverse", "pb-status-success", 4.5, "inverse text on success"),
    ContrastCheck("pb-text-inverse", "pb-status-warning", 4.5, "inverse text on warning"),
    ContrastCheck("pb-text-inverse", "pb-status-danger", 4.5, "inverse text on danger"),
]

FOCUS_CHECKS = [
    ContrastCheck("pb-focus-outline", "pb-surface-app", 3.0, "focus outline on app"),
    ContrastCheck("pb-focus-outline", "pb-surface-card", 3.0, "focus outline on card"),
]

LIGHT_SYNC_TOKENS = [
    "pb-surface-app",
    "pb-surface-shell",
    "pb-surface-card",
    "pb-surface-raised",
    "pb-surface-input",
    "pb-text-primary",
    "pb-text-secondary",
    "pb-text-tertiary",
    "pb-interactive",
    "pb-brand",
    "pb-status-success",
    "pb-status-warning",
    "pb-status-danger",
    "pb-status-info",
    "pb-focus-outline",
]


def extract_block(source: str, selector: str) -> str:
    start = source.find(selector)
    if start == -1:
        raise ValueError(f"Could not find selector block: {selector}")

    brace_start = source.find("{", start)
    if brace_start == -1:
        raise ValueError(f"Could not find opening brace for selector: {selector}")

    depth = 0
    for idx in range(brace_start, len(source)):
        char = source[idx]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[brace_start + 1 : idx]

    raise ValueError(f"Could not find closing brace for selector: {selector}")


def parse_tokens(block: str) -> dict[str, str]:
    return {match.group("name"): match.group("value").strip() for match in TOKEN_PATTERN.finditer(block)}


def parse_color(raw: str, *, tokens: dict[str, str]) -> tuple[int, int, int, float]:
    value = raw.strip()
    if value.startswith("var(--") and value.endswith(")"):
        token_name = value[6:-1].strip()
        resolved = tokens.get(token_name)
        if resolved is None:
            raise ValueError(f"Unknown token reference: {value}")
        return parse_color(resolved, tokens=tokens)

    hex_match = HEX_PATTERN.match(value)
    if hex_match:
        hex_value = hex_match.group(1)
        return (
            int(hex_value[0:2], 16),
            int(hex_value[2:4], 16),
            int(hex_value[4:6], 16),
            1.0,
        )

    rgba_match = RGBA_PATTERN.match(value)
    if rgba_match:
        return (
            int(rgba_match.group("r")),
            int(rgba_match.group("g")),
            int(rgba_match.group("b")),
            float(rgba_match.group("a")),
        )

    raise ValueError(f"Unsupported color format: {value}")


def blend_rgba(
    foreground: tuple[int, int, int, float],
    background: tuple[int, int, int, float],
) -> tuple[int, int, int]:
    fr, fg, fb, fa = foreground
    br, bg, bb, _ = background
    return (
        round((fr * fa) + (br * (1.0 - fa))),
        round((fg * fa) + (bg * (1.0 - fa))),
        round((fb * fa) + (bb * (1.0 - fa))),
    )


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    def channel(value: int) -> float:
        normalized = value / 255.0
        if normalized <= 0.03928:
            return normalized / 12.92
        return ((normalized + 0.055) / 1.055) ** 2.4

    red, green, blue = rgb
    return (0.2126 * channel(red)) + (0.7152 * channel(green)) + (0.0722 * channel(blue))


def contrast_ratio(
    foreground: tuple[int, int, int, float],
    background: tuple[int, int, int, float],
) -> float:
    fg_rgb = blend_rgba(foreground, background) if foreground[3] < 1.0 else foreground[:3]
    bg_rgb = blend_rgba(background, (255, 255, 255, 1.0)) if background[3] < 1.0 else background[:3]
    lighter = max(relative_luminance(fg_rgb), relative_luminance(bg_rgb))
    darker = min(relative_luminance(fg_rgb), relative_luminance(bg_rgb))
    return (lighter + 0.05) / (darker + 0.05)


def run_checks(theme: str, tokens: dict[str, str], checks: Iterable[ContrastCheck]) -> list[str]:
    failures: list[str] = []
    for check in checks:
        foreground = parse_color(tokens[check.foreground], tokens=tokens)
        background = parse_color(tokens[check.background], tokens=tokens)
        ratio = contrast_ratio(foreground, background)
        if ratio < check.minimum:
            failures.append(
                f"{theme}: {check.label} failed at {ratio:.2f}:1 "
                f"(needs {check.minimum:.2f}:1)"
            )
    return failures


def main() -> int:
    source = CSS_PATH.read_text()
    dark_tokens = parse_tokens(extract_block(source, ':root,\n  [data-theme="dark"]'))
    light_tokens = parse_tokens(extract_block(source, '[data-theme="light"]'))
    fallback_tokens = parse_tokens(extract_block(source, ':root:not([data-theme])'))

    failures: list[str] = []
    failures.extend(run_checks("dark", dark_tokens, [*TEXT_CHECKS, *CONTROL_CHECKS, *FOCUS_CHECKS]))
    failures.extend(run_checks("light", light_tokens, [*TEXT_CHECKS, *CONTROL_CHECKS, *FOCUS_CHECKS]))

    for token in LIGHT_SYNC_TOKENS:
        if light_tokens[token] != fallback_tokens[token]:
            failures.append(
                f"light fallback drift: {token} is {fallback_tokens[token]} in system fallback "
                f"but {light_tokens[token]} in [data-theme=\"light\"]"
            )

    if failures:
        print("Contrast audit failed:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("Contrast audit passed for Pullbox semantic tokens.")
    print("Checked:")
    print("  - normal text and semantic text tones on core surfaces")
    print("  - inverse text on interactive/status controls")
    print("  - focus outline contrast on core surfaces")
    print("  - light theme system-fallback token parity")
    return 0


if __name__ == "__main__":
    sys.exit(main())
