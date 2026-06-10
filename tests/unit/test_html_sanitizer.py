"""Tests for provider rich-HTML sanitization before UI rendering."""

from __future__ import annotations

from pullbox.core.html_sanitizer import sanitize_rich_html


def test_sanitize_rich_html_preserves_safe_description_markup() -> None:
    html = '<p><strong>Absolute Flash</strong> <a href="https://example.com">source</a></p>'

    result = sanitize_rich_html(html)

    assert "<p>" in result
    assert "<strong>Absolute Flash</strong>" in result
    assert 'href="https://example.com"' in result


def test_sanitize_rich_html_strips_script_and_event_handlers() -> None:
    html = '<p onclick="alert(1)">Safe</p><script>alert(1)</script>'

    result = sanitize_rich_html(html)

    assert "onclick" not in result
    assert "<script" not in result
    assert "Safe" in result


def test_sanitize_rich_html_strips_javascript_links() -> None:
    html = '<a href="javascript:alert(1)">bad link</a>'

    result = sanitize_rich_html(html)

    assert "javascript:" not in result
    assert "bad link" in result


def test_sanitize_rich_html_handles_empty_values() -> None:
    assert sanitize_rich_html(None) == ""
    assert sanitize_rich_html("") == ""
