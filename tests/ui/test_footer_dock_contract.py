"""Static contract tests for the shared footer dock sizing rules."""

from __future__ import annotations

import re
from pathlib import Path

BASE_TEMPLATE = Path("src/pullbox/ui/templates/base.html")
INPUT_CSS = Path("src/pullbox/ui/static/css/input.css")


def _css() -> str:
    return INPUT_CSS.read_text(encoding="utf-8")


def _base_template() -> str:
    return BASE_TEMPLATE.read_text(encoding="utf-8")


def _rule_block(css: str, selector: str) -> str:
    match = re.search(rf"{re.escape(selector)}\s*\{{(?P<body>.*?)\n\s*\}}", css, re.DOTALL)
    assert match is not None, f"Missing CSS selector: {selector}"
    return match.group("body")


def _rule_blocks(css: str, selector: str) -> list[str]:
    matches = re.finditer(rf"{re.escape(selector)}\s*\{{(?P<body>.*?)\n\s*\}}", css, re.DOTALL)
    blocks = [match.group("body") for match in matches]
    assert blocks, f"Missing CSS selector: {selector}"
    return blocks


def test_footer_dock_declares_only_stats_and_pagination_heights() -> None:
    css = _css()
    inner = _rule_block(css, ".page-dock-inner")
    pagination = _rule_block(css, ".page-dock-inner:has(.page-dock-pagination)")

    assert "--page-dock-height-status: 2rem;" in inner
    assert "--page-dock-height-pagination: 2.5rem;" in inner
    assert "height: var(--page-dock-height-status);" in inner
    assert "height: var(--page-dock-height-pagination);" in pagination


def test_footer_dock_prevents_wrapping_into_extra_footer_heights() -> None:
    css = _css()
    inner = _rule_block(css, ".page-dock-inner")
    status = _rule_block(css, ".page-dock-status")

    assert "flex-wrap: nowrap;" in inner
    assert "flex-wrap: nowrap;" in status
    assert "overflow-x: auto;" in status
    assert ".page-dock-status::-webkit-scrollbar" in css


def test_footer_dock_pagination_controls_show_click_cursor() -> None:
    css = _css()
    controls = _rule_block(
        css,
        ".page-dock-pagination nav > a,\n  .page-dock-pagination nav > button",
    )

    assert "cursor: pointer;" in controls


def test_page_shells_do_not_add_competing_footer_clearance() -> None:
    css = _css()
    page = _rule_block(css, ".admin-workspace-page")
    downloads = _rule_block(css, ".downloads-view")
    expected_clearance = "padding-bottom: var(--pb-page-footer-clearance);"

    assert "min-h-full" not in page
    assert "min-h-0" in page
    assert "pb-4" not in page
    assert "padding: 0 0 var(--pb-page-footer-clearance);" in downloads
    assert "5rem" not in downloads
    last_card_selector = (
        ".admin-workspace-content .space-y-6 > .section-card:not(:has(~ .section-card))"
    )
    assert last_card_selector in css
    assert ".section-card:last-of-type" not in css

    for selector in [
        ".admin-workspace-body",
        ".dashboard-mission-page",
        ".series-domain-page",
        ".series-results-shell",
        ".utilities-page",
    ]:
        for block in _rule_blocks(css, selector):
            assert expected_clearance in block
            assert re.search(r"@apply[^;]*\bpb-", block) is None
    for block in _rule_blocks(css, ".series-page-shell"):
        assert "padding-bottom" not in block
        assert re.search(r"@apply[^;]*\bpb-", block) is None


def test_results_shell_uses_content_sized_footer_clearance() -> None:
    css = _css()
    shell = _rule_block(css, ".series-results-shell")

    assert "flex-1" not in shell
    assert "flex-none" in shell
    assert re.search(r"@apply[^;]*\bpb-", shell) is None
    assert "padding-bottom: var(--pb-page-footer-clearance);" in shell


def test_content_scroll_container_renders_footer_clearance_globally() -> None:
    html = _base_template()
    css = _css()
    content_match = re.search(r'<div id="content" class="(?P<classes>[^"]+)"', html)
    assert content_match is not None

    content_block_index = html.index("{% block content %}")
    script_block_index = html.index("{% block scripts %}")
    clearance_index = html.index('data-testid="page-footer-clearance"')
    content_classes = content_match.group("classes").split()
    content_clearance = _rule_block(css, "body:has(#page-footer-dock:not(:empty)) #content")
    clearance = _rule_block(css, ".page-footer-clearance")

    assert content_block_index < clearance_index < script_block_index
    assert 'class="page-footer-clearance"' in html
    assert "padding-bottom: var(--pb-page-footer-clearance);" in content_clearance
    assert "#content:has(" in css
    assert "height: var(--pb-page-footer-clearance);" in clearance
    assert "flex: 0 0 var(--pb-page-footer-clearance);" in clearance
    assert "pointer-events: none;" in clearance
    assert "pb-5" not in content_classes
    assert "sm:pb-6" not in content_classes


def test_main_area_is_not_a_focus_scroll_container() -> None:
    html = _base_template()

    assert 'id="main-area" class="relative flex h-[100dvh] flex-col overflow-hidden"' in html
    assert "#main-area { overflow: clip; }" in html


def test_toggle_inputs_are_positioned_inside_their_visible_label() -> None:
    css = _css()
    toggle_label = _rule_block(css, "label:has(> .toggle-input + .toggle-switch)")
    toggle_input = _rule_block(css, ".toggle-input")

    assert "position: relative;" in toggle_label
    assert "position: absolute;" in toggle_input
