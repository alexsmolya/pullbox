"""Tests for indexer XML/JSON parsing — new code from ESM sprint.

Covers:
- _parse_newznab_attrs: scanning both newznab and torznab namespaces
- _parse_item_common: extracting info_url from <comments> / <guid>
- Prowlarr info_url extraction from infoUrl / commentUrl / guid

Run:
    pytest tests/providers/test_indexer_parsing.py -v
"""

from __future__ import annotations

from xml.etree import ElementTree

from pullbox.providers.indexer.newznab import (
    NewznabError,
    _parse_capabilities,
    _parse_item_common,
    _parse_newznab_attrs,
)

# ── _parse_newznab_attrs ──────────────────────────────────────────────


class TestParseNewznabAttrs:
    """Tests for dual-namespace attribute parsing."""

    def test_parses_newznab_attrs(self) -> None:
        """Standard newznab:attr elements are parsed."""
        xml = """
        <item xmlns:newznab="http://www.newznab.com/DTD/2010/feeds/attributes/">
          <newznab:attr name="size" value="123456"/>
          <newznab:attr name="grabs" value="10"/>
        </item>
        """
        item = ElementTree.fromstring(xml)
        attrs = _parse_newznab_attrs(item)
        assert attrs["size"] == "123456"
        assert attrs["grabs"] == "10"

    def test_parses_torznab_attrs(self) -> None:
        """torznab:attr elements are also parsed."""
        xml = """
        <item xmlns:torznab="http://torznab.com/schemas/2015/feed">
          <torznab:attr name="seeders" value="19"/>
          <torznab:attr name="peers" value="25"/>
        </item>
        """
        item = ElementTree.fromstring(xml)
        attrs = _parse_newznab_attrs(item)
        assert attrs["seeders"] == "19"
        assert attrs["peers"] == "25"

    def test_parses_both_namespaces(self) -> None:
        """Items with both newznab and torznab attrs return all values."""
        xml = """
        <item xmlns:newznab="http://www.newznab.com/DTD/2010/feeds/attributes/"
              xmlns:torznab="http://torznab.com/schemas/2015/feed">
          <newznab:attr name="category" value="7030"/>
          <torznab:attr name="seeders" value="5"/>
        </item>
        """
        item = ElementTree.fromstring(xml)
        attrs = _parse_newznab_attrs(item)
        assert attrs["category"] == "7030"
        assert attrs["seeders"] == "5"

    def test_empty_name_skipped(self) -> None:
        """Attributes with empty name are ignored."""
        xml = """
        <item xmlns:newznab="http://www.newznab.com/DTD/2010/feeds/attributes/">
          <newznab:attr name="" value="junk"/>
          <newznab:attr name="grabs" value="5"/>
        </item>
        """
        item = ElementTree.fromstring(xml)
        attrs = _parse_newznab_attrs(item)
        assert "" not in attrs
        assert attrs["grabs"] == "5"

    def test_no_attrs_returns_empty(self) -> None:
        """Item with no namespace attributes returns empty dict."""
        xml = "<item><title>Nothing</title></item>"
        item = ElementTree.fromstring(xml)
        attrs = _parse_newznab_attrs(item)
        assert attrs == {}


# ── _parse_item_common ────────────────────────────────────────────────


class TestParseItemCommon:
    """Tests for shared RSS item parsing, focusing on info_url extraction."""

    def test_info_url_from_comments(self) -> None:
        """info_url is taken from <comments> element when present."""
        xml = """
        <item>
          <title>Batman 001.cbz</title>
          <link>https://dl.example.com/nzb</link>
          <comments>https://indexer.example.com/details/12345</comments>
          <guid>some-internal-guid</guid>
        </item>
        """
        item = ElementTree.fromstring(xml)
        result = _parse_item_common(item)
        assert result[0] == "Batman 001.cbz"  # title
        assert result[6] == "https://indexer.example.com/details/12345"  # info_url

    def test_info_url_from_guid_http(self) -> None:
        """info_url falls back to <guid> when it starts with http."""
        xml = """
        <item>
          <title>Batman 002.cbz</title>
          <link>https://dl.example.com/nzb</link>
          <guid>https://indexer.example.com/details/67890</guid>
        </item>
        """
        item = ElementTree.fromstring(xml)
        *_, info_url = _parse_item_common(item)
        assert info_url == "https://indexer.example.com/details/67890"

    def test_info_url_none_when_guid_not_http(self) -> None:
        """info_url is None when <guid> is not a URL and no <comments>."""
        xml = """
        <item>
          <title>Batman 003.cbz</title>
          <link>https://dl.example.com/nzb</link>
          <guid>abc-internal-id-123</guid>
        </item>
        """
        item = ElementTree.fromstring(xml)
        *_, info_url = _parse_item_common(item)
        assert info_url is None

    def test_info_url_none_when_no_comments_no_guid(self) -> None:
        """info_url is None when neither <comments> nor useful <guid> exist."""
        xml = """
        <item>
          <title>Batman 004.cbz</title>
          <link>https://dl.example.com/nzb</link>
        </item>
        """
        item = ElementTree.fromstring(xml)
        *_, info_url = _parse_item_common(item)
        assert info_url is None

    def test_returns_seven_tuple(self) -> None:
        """_parse_item_common returns a 7-element tuple."""
        xml = """
        <item>
          <title>Test</title>
          <link>https://example.com</link>
        </item>
        """
        item = ElementTree.fromstring(xml)
        result = _parse_item_common(item)
        assert len(result) == 7


# ── Prowlarr info_url ─────────────────────────────────────────────────


class TestProwlarrInfoUrl:
    """Tests for Prowlarr JSON info_url extraction."""

    def test_info_url_from_info_url_field(self) -> None:
        """infoUrl field is used when present."""
        from pullbox.providers.indexer.prowlarr import ProwlarrIndexer

        data = [
            {
                "title": "Batman 001",
                "indexer": "TorrentGalaxy",
                "protocol": "torrent",
                "downloadUrl": "https://dl.example.com/t/1",
                "size": 100000,
                "infoUrl": "https://torrentgalaxy.to/detail/12345",
                "seeders": 10,
                "leechers": 2,
            }
        ]
        results = ProwlarrIndexer._parse_api_results(data)
        assert results[0].info_url == "https://torrentgalaxy.to/detail/12345"

    def test_info_url_from_comment_url(self) -> None:
        """commentUrl field is used when infoUrl is absent."""
        from pullbox.providers.indexer.prowlarr import ProwlarrIndexer

        data = [
            {
                "title": "Batman 001",
                "indexer": "NZBgeek",
                "protocol": "usenet",
                "downloadUrl": "https://dl.example.com/nzb/1",
                "size": 50000,
                "commentUrl": "https://nzbgeek.info/details/67890",
            }
        ]
        results = ProwlarrIndexer._parse_api_results(data)
        assert results[0].info_url == "https://nzbgeek.info/details/67890"

    def test_info_url_from_guid_http(self) -> None:
        """guid field is used as fallback when it starts with http."""
        from pullbox.providers.indexer.prowlarr import ProwlarrIndexer

        data = [
            {
                "title": "Batman 001",
                "indexer": "IPT",
                "protocol": "torrent",
                "guid": "https://iptorrents.com/t/12345",
                "size": 75000,
                "seeders": 5,
                "leechers": 1,
            }
        ]
        results = ProwlarrIndexer._parse_api_results(data)
        assert results[0].info_url == "https://iptorrents.com/t/12345"

    def test_info_url_none_when_no_url_fields(self) -> None:
        """info_url is None when no URL-like fields exist."""
        from pullbox.providers.indexer.prowlarr import ProwlarrIndexer

        data = [
            {
                "title": "Batman 001",
                "indexer": "Unknown",
                "protocol": "usenet",
                "downloadUrl": "https://dl.example.com/nzb/1",
                "guid": "internal-id-only",
                "size": 50000,
            }
        ]
        results = ProwlarrIndexer._parse_api_results(data)
        assert results[0].info_url is None


class TestNewznabXmlSafety:
    """External Newznab XML must reject entity expansion payloads."""

    def test_capabilities_xml_entities_are_rejected(self) -> None:
        xml = """\
<!DOCTYPE caps [
  <!ENTITY injected "book">
]>
<caps>
  <categories>
    <category id="7030" name="&injected;"/>
  </categories>
</caps>
"""

        try:
            _parse_capabilities(xml)
        except NewznabError as exc:
            assert "XML" in str(exc)
        else:  # pragma: no cover - makes a regression very loud
            raise AssertionError("Expected entity-bearing Newznab XML to be rejected")
