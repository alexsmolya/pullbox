"""Tests for Jackett manager discovery and connection health."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest

from pullbox.providers.indexer.jackett import JackettClient, JackettError

if TYPE_CHECKING:
    from collections.abc import Callable


_INDEXERS_XML = """<?xml version="1.0" encoding="utf-8"?>
<indexers>
  <indexer id="1337x" configured="true">
    <title>1337x</title>
    <description>Public tracker</description>
    <link>https://1337x.example/</link>
    <language>en-US</language>
    <type>public</type>
    <caps>
      <searching>
        <search available="yes" supportedParams="q" />
        <tv-search available="yes" supportedParams="q,season,ep" />
      </searching>
      <categories>
        <category id="7000" name="Books">
          <subcat id="7030" name="Comics" />
        </category>
        <category id="8000" name="Other" />
      </categories>
    </caps>
  </indexer>
  <indexer id="aniRena" configured="true">
    <title>AniRena</title>
    <caps>
      <searching>
        <search available="yes" supportedParams="q" />
      </searching>
      <categories>
        <category id="5070" name="Anime" />
      </categories>
    </caps>
  </indexer>
</indexers>
"""


def _transport(
    handler: Callable[[httpx.Request], httpx.Response],
) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_configured_indexers_request_and_parse_individual_feed_metadata() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text=_INDEXERS_XML, request=request)

    client = JackettClient(
        url="http://jackett:9117/",
        api_key="secret-key",
        transport=_transport(handler),
    )
    try:
        indexers = await client.get_configured_indexers()
    finally:
        await client.close()

    assert len(requests) == 1
    assert requests[0].url.path == "/api/v2.0/indexers/all/results/torznab/api"
    assert dict(requests[0].url.params) == {
        "apikey": "secret-key",
        "t": "indexers",
        "configured": "true",
    }
    assert [(item.id, item.name) for item in indexers] == [
        ("1337x", "1337x"),
        ("aniRena", "AniRena"),
    ]
    assert indexers[0].description == "Public tracker"
    assert indexers[0].categories == ("7000", "7030", "8000")
    assert indexers[0].search_modes == ("search", "tv-search")


@pytest.mark.asyncio
async def test_connection_health_reports_configured_tracker_count() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=_INDEXERS_XML, request=request)

    client = JackettClient(
        url="http://jackett:9117",
        api_key="secret-key",
        transport=_transport(handler),
    )
    try:
        health = await client.test_connection()
    finally:
        await client.close()

    assert health.healthy is True
    assert health.message == "Jackett: 2 configured tracker(s)"
    assert health.details == {"indexer_count": "2"}


@pytest.mark.asyncio
async def test_malformed_xml_fails_closed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<indexers><indexer>", request=request)

    client = JackettClient(
        url="http://jackett:9117",
        api_key="secret-key",
        transport=_transport(handler),
    )
    try:
        with pytest.raises(JackettError, match="invalid indexer response"):
            await client.get_configured_indexers()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_oversized_xml_is_rejected_before_parsing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 1_048_577, request=request)

    client = JackettClient(
        url="http://jackett:9117",
        api_key="secret-key",
        transport=_transport(handler),
    )
    try:
        with pytest.raises(JackettError, match="response exceeded"):
            await client.get_configured_indexers()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_invalid_tracker_identifier_is_skipped() -> None:
    body = _INDEXERS_XML.replace('id="1337x"', 'id="../../escape"')

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body, request=request)

    client = JackettClient(
        url="http://jackett:9117",
        api_key="secret-key",
        transport=_transport(handler),
    )
    try:
        indexers = await client.get_configured_indexers()
    finally:
        await client.close()

    assert [item.id for item in indexers] == ["aniRena"]


@pytest.mark.asyncio
async def test_request_failures_do_not_expose_the_api_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized", request=request)

    client = JackettClient(
        url="http://jackett:9117",
        api_key="do-not-leak",
        transport=_transport(handler),
    )
    try:
        with pytest.raises(JackettError) as exc_info:
            await client.get_configured_indexers()
    finally:
        await client.close()

    assert "HTTP 401" in str(exc_info.value)
    assert "do-not-leak" not in str(exc_info.value)
