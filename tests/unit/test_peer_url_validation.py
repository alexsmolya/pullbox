"""Tests for operator-configured peer/service URL validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pullbox.models.download import DownloadClientType
from pullbox.models.indexer import IndexerType
from pullbox.schemas.client import ClientCreate, ClientUpdate
from pullbox.schemas.indexer import (
    IndexerCreate,
    IndexerUpdate,
    JackettSyncRequest,
    ProwlarrSyncRequest,
)


def test_download_client_url_accepts_http_and_normalizes_trailing_slash() -> None:
    body = ClientCreate(
        name="SAB",
        client_type=DownloadClientType.SABNZBD,
        url=" http://sabnzbd.local:8080/ ",
    )

    assert body.url == "http://sabnzbd.local:8080"


@pytest.mark.parametrize(
    "url",
    [
        "ftp://host",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "localhost:8080",
        "http://bad host",
    ],
)
def test_download_client_url_rejects_non_http_peer_urls(url: str) -> None:
    with pytest.raises(ValidationError):
        ClientUpdate(url=url)


def test_indexer_url_accepts_https_and_normalizes_trailing_slash() -> None:
    body = IndexerCreate(
        name="Prowlarr",
        indexer_type=IndexerType.TORZNAB,
        url="https://prowlarr.local:9696/",
        api_key="secret",
    )

    assert body.url == "https://prowlarr.local:9696"


@pytest.mark.parametrize("url", ["ftp://indexer.local", "http://", "https:///missing-host"])
def test_indexer_url_rejects_invalid_peer_urls(url: str) -> None:
    with pytest.raises(ValidationError):
        IndexerUpdate(url=url)


def test_prowlarr_sync_url_rejects_embedded_credentials() -> None:
    with pytest.raises(ValidationError):
        ProwlarrSyncRequest(
            prowlarr_url="https://user:pass@prowlarr.local",
            prowlarr_api_key="secret",
        )


def test_jackett_sync_url_normalizes_and_rejects_embedded_credentials() -> None:
    request = JackettSyncRequest(
        jackett_url=" https://jackett.local:9117/ ",
        jackett_api_key="secret",
    )
    assert request.jackett_url == "https://jackett.local:9117"

    with pytest.raises(ValidationError):
        JackettSyncRequest(
            jackett_url="https://user:pass@jackett.local:9117",
            jackett_api_key="secret",
        )
