"""Tests for low-level ComicInfo.xml parsing."""

from __future__ import annotations

from pullbox.core.comicinfo import parse_comicinfo


def test_parse_comicinfo_rejects_xml_entities() -> None:
    xml = """\
<!DOCTYPE ComicInfo [
  <!ENTITY injected "Injected Series">
]>
<ComicInfo><Series>&injected;</Series></ComicInfo>
"""

    result = parse_comicinfo(xml)

    assert result.series is None
