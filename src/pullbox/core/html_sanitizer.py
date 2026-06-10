"""Safe rendering helpers for provider-sourced rich HTML."""

from __future__ import annotations

from html import escape
from html.parser import HTMLParser
from urllib.parse import urlparse

_ALLOWED_TAGS = frozenset(
    {
        "a",
        "b",
        "blockquote",
        "br",
        "em",
        "i",
        "li",
        "ol",
        "p",
        "span",
        "strong",
        "u",
        "ul",
    }
)
_VOID_TAGS = frozenset({"br"})
_DROP_WITH_CONTENT = frozenset({"script", "style", "iframe", "object", "embed", "svg", "math"})
_ALLOWED_ATTRS = {
    "a": frozenset({"href", "title", "target", "rel"}),
    "span": frozenset({"title"}),
}
_ALLOWED_URL_SCHEMES = frozenset({"", "http", "https", "mailto"})


def _safe_url(value: str) -> bool:
    """Return True when a URL is safe to render in rich text."""
    parsed = urlparse(value.strip())
    return parsed.scheme.lower() in _ALLOWED_URL_SCHEMES


class _RichHtmlSanitizer(HTMLParser):
    """Allowlist sanitizer for external comic metadata descriptions."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._drop_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in _DROP_WITH_CONTENT:
            self._drop_depth += 1
            return
        if self._drop_depth or tag not in _ALLOWED_TAGS:
            return

        allowed_attrs = _ALLOWED_ATTRS.get(tag, frozenset())
        rendered_attrs: list[str] = []
        for name, raw_value in attrs:
            name = name.lower()
            if name not in allowed_attrs or raw_value is None:
                continue
            value = raw_value.strip()
            if name == "href" and not _safe_url(value):
                continue
            rendered_attrs.append(f'{name}="{escape(value, quote=True)}"')

        if tag == "a":
            attr_names = {attr.split("=", 1)[0] for attr in rendered_attrs}
            if "target" in attr_names and "rel" not in attr_names:
                rendered_attrs.append('rel="noopener noreferrer"')

        suffix = f" {' '.join(rendered_attrs)}" if rendered_attrs else ""
        self._parts.append(f"<{tag}{suffix}>")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _DROP_WITH_CONTENT and self._drop_depth:
            self._drop_depth -= 1
            return
        if self._drop_depth or tag not in _ALLOWED_TAGS or tag in _VOID_TAGS:
            return
        self._parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self._drop_depth:
            self._parts.append(escape(data))

    def handle_entityref(self, name: str) -> None:
        if not self._drop_depth:
            self._parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if not self._drop_depth:
            self._parts.append(f"&#{name};")

    def result(self) -> str:
        """Return the sanitized HTML fragment."""
        return "".join(self._parts)


def sanitize_rich_html(value: str | None) -> str:
    """Sanitize provider-sourced rich HTML for safe template rendering."""
    if not value:
        return ""

    parser = _RichHtmlSanitizer()
    parser.feed(value)
    parser.close()
    return parser.result()
