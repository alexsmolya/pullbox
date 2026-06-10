"""Tests for SABnzbd download client implementation.

Covers the local NZB fetch + upload contract so SAB does not need to
reach indexer download URLs directly.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from pullbox.providers.download.sabnzbd import SABnzbdClient, SABnzbdError

_FAKE_NZB_CONTENT = b"<?xml version='1.0'?><nzb>fake</nzb>"


def _make_client(**kwargs: Any) -> SABnzbdClient:
    defaults: dict[str, Any] = {
        "url": "http://localhost:8080",
        "api_key": "secret",
    }
    defaults.update(kwargs)
    return SABnzbdClient(**defaults)


def _make_response(
    *,
    status_code: int = 200,
    content: bytes = _FAKE_NZB_CONTENT,
    content_type: str = "application/x-nzb",
    json_data: dict[str, Any] | None = None,
) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.content = content
    response.headers = {"content-type": content_type}
    response.raise_for_status = MagicMock()
    response.json.return_value = json_data or {}
    return response


@pytest.mark.asyncio
class TestAddNzb:
    """Tests for SABnzbdClient.add_nzb()."""

    async def test_add_nzb_downloads_locally_then_uploads_to_sab(self) -> None:
        client = _make_client(category="comics", priority="1", post_processing="3")
        fetch_response = _make_response()
        upload_response = _make_response(json_data={"status": True, "nzo_ids": ["nzo-123"]})
        client._client.get = AsyncMock(return_value=fetch_response)  # type: ignore[method-assign]
        client._client.post = AsyncMock(return_value=upload_response)  # type: ignore[method-assign]

        result = await client.add_nzb("http://example.com/test.nzb", "Batman 001")

        assert result == "nzo-123"
        client._client.get.assert_awaited_once_with(  # type: ignore[attr-defined]
            "http://example.com/test.nzb",
            follow_redirects=True,
        )
        client._client.post.assert_awaited_once()  # type: ignore[attr-defined]

        _, kwargs = client._client.post.call_args  # type: ignore[attr-defined]
        assert kwargs["params"]["mode"] == "addfile"
        assert kwargs["params"]["cat"] == "comics"
        assert kwargs["params"]["priority"] == "1"
        assert kwargs["params"]["pp"] == "3"
        assert kwargs["params"]["nzbname"] == "Batman 001"
        file_name, file_bytes, content_type = kwargs["files"]["nzbfile"]
        assert file_name == "Batman 001.nzb"
        assert file_bytes == _FAKE_NZB_CONTENT
        assert content_type == "application/x-nzb"

    async def test_add_nzb_preserves_existing_extension(self) -> None:
        client = _make_client()
        client._client.get = AsyncMock(return_value=_make_response())  # type: ignore[method-assign]
        client._client.post = AsyncMock(  # type: ignore[method-assign]
            return_value=_make_response(json_data={"status": True, "nzo_ids": ["nzo-456"]})
        )

        await client.add_nzb("http://example.com/test.nzb", "Batman 001.nzb")

        _, kwargs = client._client.post.call_args  # type: ignore[attr-defined]
        file_name, *_ = kwargs["files"]["nzbfile"]
        assert file_name == "Batman 001.nzb"

    async def test_add_nzb_accepts_xml_body_with_generic_content_type(self) -> None:
        client = _make_client()
        client._client.get = AsyncMock(  # type: ignore[method-assign]
            return_value=_make_response(content_type="application/octet-stream")
        )
        client._client.post = AsyncMock(  # type: ignore[method-assign]
            return_value=_make_response(json_data={"status": True, "nzo_ids": ["nzo-789"]})
        )

        result = await client.add_nzb("http://example.com/test.nzb", "Batman 001")

        assert result == "nzo-789"

    async def test_add_nzb_rejects_non_nzb_response(self) -> None:
        client = _make_client()
        client._client.get = AsyncMock(  # type: ignore[method-assign]
            return_value=_make_response(
                content=b"<html><body>login page</body></html>",
                content_type="text/html",
            )
        )

        with pytest.raises(SABnzbdError, match="URL did not return NZB content"):
            await client.add_nzb("http://example.com/test.nzb", "Batman 001")

    async def test_add_nzb_download_timeout_raises_clear_error(self) -> None:
        client = _make_client()
        client._client.get = AsyncMock(side_effect=httpx.TimeoutException("boom"))  # type: ignore[method-assign]

        with pytest.raises(
            SABnzbdError,
            match="Failed to download NZB from URL: Request timed out",
        ):
            await client.add_nzb("http://example.com/test.nzb", "Batman 001")

    async def test_add_nzb_upload_http_error_raises(self) -> None:
        client = _make_client()
        fetch_response = _make_response()
        upload_response = _make_response(status_code=500)
        upload_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "server error",
            request=MagicMock(),
            response=MagicMock(status_code=500),
        )
        client._client.get = AsyncMock(return_value=fetch_response)  # type: ignore[method-assign]
        client._client.post = AsyncMock(return_value=upload_response)  # type: ignore[method-assign]

        with pytest.raises(SABnzbdError, match="HTTP 500"):
            await client.add_nzb("http://example.com/test.nzb", "Batman 001")

    async def test_add_nzb_upload_api_error_raises(self) -> None:
        client = _make_client()
        client._client.get = AsyncMock(return_value=_make_response())  # type: ignore[method-assign]
        client._client.post = AsyncMock(  # type: ignore[method-assign]
            return_value=_make_response(json_data={"status": False, "error": "Upload rejected"})
        )

        with pytest.raises(SABnzbdError, match="Upload rejected"):
            await client.add_nzb("http://example.com/test.nzb", "Batman 001")

    async def test_add_nzb_missing_nzo_id_raises(self) -> None:
        client = _make_client()
        client._client.get = AsyncMock(return_value=_make_response())  # type: ignore[method-assign]
        client._client.post = AsyncMock(  # type: ignore[method-assign]
            return_value=_make_response(json_data={"status": True, "nzo_ids": []})
        )

        with pytest.raises(SABnzbdError, match="No nzo_id returned"):
            await client.add_nzb("http://example.com/test.nzb", "Batman 001")


@pytest.mark.asyncio
class TestAddTorrent:
    """Verify add_torrent raises NotImplementedError."""

    async def test_add_torrent_raises(self) -> None:
        client = _make_client()

        with pytest.raises(NotImplementedError, match="does not support torrent"):
            await client.add_torrent("magnet:?xt=urn:btih:abc", "Test")
