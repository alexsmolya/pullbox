"""Bounded structural HTML extraction for explicitly supported host pages."""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser


@dataclass(slots=True)
class ParsedForm:
    action: str
    method: str
    fields: dict[str, str] = field(default_factory=dict)


class HostPageParser(HTMLParser):
    """Extract only known anchor and form attributes without script execution."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: dict[str, str] = {}
        self.forms: dict[str, ParsedForm] = {}
        self.class_names: set[str] = set()
        self.iframe_sources: list[str] = []
        self._active_form: ParsedForm | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name.lower(): value or "" for name, value in attrs}
        self.class_names.update(values.get("class", "").casefold().split())
        if tag.lower() == "iframe" and values.get("src"):
            self.iframe_sources.append(values["src"])
        if tag.lower() == "a" and values.get("id") and values.get("href"):
            self.anchors[values["id"]] = values["href"]
            return
        if tag.lower() == "form" and (values.get("id") or values.get("name")):
            form = ParsedForm(
                action=values.get("action", ""),
                method=values.get("method", "GET").upper(),
            )
            self.forms[values.get("id") or values["name"]] = form
            self._active_form = form
            return
        if tag.lower() == "input" and self._active_form is not None and values.get("name"):
            self._active_form.fields[values["name"]] = values.get("value", "")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "form":
            self._active_form = None


def parse_host_page(document: str) -> HostPageParser:
    parser = HostPageParser()
    parser.feed(document)
    parser.close()
    return parser
