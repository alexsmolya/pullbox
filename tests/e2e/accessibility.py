"""Shared accessibility helpers for Playwright WCAG regression coverage."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from playwright.sync_api import Page


ROOT = Path(__file__).resolve().parents[2]
AXE_SCRIPT = ROOT / "node_modules" / "axe-core" / "axe.min.js"
ARTIFACTS_DIR = ROOT / "test-results" / "accessibility"
WCAG_AA_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]


def _slugify(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", name).strip("-").lower()


def ensure_axe(page: Page) -> None:
    if not AXE_SCRIPT.exists():
        raise RuntimeError(
            "axe-core is not installed. Run `npm install` or `npm install --save-dev axe-core`."
        )

    if page.evaluate("() => Boolean(window.axe)"):
        return

    page.add_script_tag(path=str(AXE_SCRIPT))
    page.wait_for_function("() => Boolean(window.axe)")


def run_axe(
    page: Page,
    *,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> dict[str, Any]:
    ensure_axe(page)
    return page.evaluate(
        """async ({ include, exclude, tags }) => {
            const context = {};
            if (include.length) {
              context.include = include.map((selector) => [selector]);
            }
            if (exclude.length) {
              context.exclude = exclude.map((selector) => [selector]);
            }

            return await window.axe.run(
              Object.keys(context).length ? context : document,
              {
                runOnly: {
                  type: 'tag',
                  values: tags,
                },
                resultTypes: ['violations', 'incomplete'],
              }
            );
        }""",
        {
            "include": include or [],
            "exclude": exclude or [],
            "tags": WCAG_AA_TAGS,
        },
    )


def assert_no_axe_violations(
    page: Page,
    *,
    name: str,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> None:
    results = run_axe(page, include=include, exclude=exclude)
    violations = results.get("violations", [])
    incomplete = results.get("incomplete", [])
    if incomplete:
        ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        incomplete_path = ARTIFACTS_DIR / f"{_slugify(name)}-incomplete.json"
        incomplete_path.write_text(json.dumps(incomplete, indent=2))

    if not violations:
        return

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    slug = _slugify(name)
    page.screenshot(path=str(ARTIFACTS_DIR / f"{slug}.png"), full_page=True)

    summary = [
        {
            "id": violation["id"],
            "impact": violation["impact"],
            "description": violation["description"],
            "help": violation["help"],
            "helpUrl": violation["helpUrl"],
            "nodes": [
                {
                    "target": node["target"],
                    "failureSummary": node.get("failureSummary"),
                }
                for node in violation["nodes"]
            ],
        }
        for violation in violations
    ]

    report_path = ARTIFACTS_DIR / f"{slug}.json"
    report_path.write_text(json.dumps(summary, indent=2))

    raise AssertionError(
        f"{name} has {len(violations)} accessibility violation(s). "
        f"See {report_path} for details.\n{json.dumps(summary, indent=2)}"
    )
