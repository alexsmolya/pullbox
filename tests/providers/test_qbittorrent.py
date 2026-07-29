"""Tests for qBittorrent download client implementation."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from pullbox.providers.download.qbittorrent import QBittorrentClient, QBittorrentError

_MAGNET_HASH = "abcdef1234567890abcdef1234567890abcdef12"


def _make_client(**kwargs: Any) -> QBittorrentClient:
    defaults: dict[str, Any] = {
        "url": "http://localhost:8080",
        "username": "admin",
        "password": "secret",
    }
    defaults.update(kwargs)
    return QBittorrentClient(**defaults)


def _make_response(
    *,
    status_code: int = 200,
    json_data: Any = None,
    text: str = "",
    headers: dict[str, str] | None = None,
) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.headers = headers or {}
    response.text = text
    response.json.return_value = [] if json_data is None else json_data
    response.raise_for_status = MagicMock()
    return response


@pytest.mark.asyncio
class TestAuthenticationAndRequests:
    """Tests for qBittorrent auth and request plumbing."""

    async def test_request_reauthenticates_once_after_expired_session(self) -> None:
        client = _make_client()
        client._authenticated = True
        client._login = AsyncMock()  # type: ignore[method-assign]
        success = _make_response(text="ok")
        client._client.request = AsyncMock(  # type: ignore[method-assign]
            side_effect=[
                _make_response(status_code=403),
                success,
            ]
        )

        response = await client._request("GET", "/app/version")

        assert response is success
        client._login.assert_awaited_once()  # type: ignore[attr-defined]
        assert client._client.request.await_count == 2  # type: ignore[attr-defined]

    async def test_request_http_error_raises_provider_error(self) -> None:
        client = _make_client()
        client._authenticated = True
        client._client.request = AsyncMock(  # type: ignore[method-assign]
            return_value=_make_response(status_code=500)
        )

        with pytest.raises(QBittorrentError, match="HTTP 500"):
            await client._request("GET", "/app/version")

    async def test_redirecting_download_url_resolves_to_magnet(self) -> None:
        client = _make_client()
        redirected_magnet = f"magnet:?xt=urn:btih:{_MAGNET_HASH}&dn=Batman"
        client._client.request = AsyncMock(  # type: ignore[method-assign]
            return_value=_make_response(
                status_code=302,
                headers={"location": redirected_magnet},
            )
        )

        result = await client._resolve_redirected_magnet_url(
            "https://indexer.example/download/123",
            MagicMock(),
        )

        assert result == redirected_magnet


@pytest.mark.asyncio
class TestAddTorrent:
    """Tests for qBittorrent torrent submission."""

    async def test_add_nzb_raises_not_supported(self) -> None:
        client = _make_client()

        with pytest.raises(NotImplementedError, match="does not support NZB"):
            await client.add_nzb("https://example.com/test.nzb", "Batman 001")

    async def test_add_existing_magnet_returns_extracted_hash_and_submits_options(self) -> None:
        client = _make_client(
            category="comics",
            content_layout="Original",
            ratio_limit=1.5,
            seeding_time_limit=120,
        )
        client._request = AsyncMock(  # type: ignore[method-assign]
            side_effect=[
                _make_response(json_data=[{"hash": _MAGNET_HASH}]),
                _make_response(text="Ok."),
            ]
        )

        result = await client.add_torrent(
            f"magnet:?xt=urn:btih:{_MAGNET_HASH}&dn=Batman",
            "Batman 001",
        )

        assert result == _MAGNET_HASH
        add_call = client._request.await_args_list[1]  # type: ignore[attr-defined]
        assert add_call.args == ("POST", "/torrents/add")
        assert add_call.kwargs["data"] == {
            "urls": f"magnet:?xt=urn:btih:{_MAGNET_HASH}&dn=Batman",
            "rename": "Batman 001",
            "category": "comics",
            "contentLayout": "Original",
            "ratioLimit": "1.5",
            "seedingTimeLimit": "120",
        }

    async def test_add_non_magnet_raises_when_client_accepts_but_list_does_not_change(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client = _make_client()
        existing = [{"hash": "existing", "name": "Old Torrent"}]
        client._request = AsyncMock(  # type: ignore[method-assign]
            side_effect=[
                _make_response(json_data=existing),
                _make_response(text="Ok."),
                *[_make_response(json_data=existing) for _ in range(6)],
            ]
        )
        monkeypatch.setattr("asyncio.sleep", AsyncMock())

        with pytest.raises(QBittorrentError, match="Torrent was not added"):
            await client.add_torrent("https://example.com/download.torrent", "Batman 001")

    async def test_add_torrent_data_uploads_descriptor_bytes(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client = _make_client(category="comics")
        client._request = AsyncMock(  # type: ignore[method-assign]
            side_effect=[
                _make_response(json_data=[]),
                _make_response(text="Ok."),
                _make_response(json_data=[{"hash": "new-hash", "name": "Batman 001"}]),
            ]
        )
        monkeypatch.setattr("asyncio.sleep", AsyncMock())

        result = await client.add_torrent_data(b"torrent-bytes", "Batman 001")

        assert result == "new-hash"
        add_call = client._request.await_args_list[1]  # type: ignore[attr-defined]
        assert add_call.args == ("POST", "/torrents/add")
        assert add_call.kwargs["data"] == {"rename": "Batman 001", "category": "comics"}
        assert add_call.kwargs["files"] == {
            "torrents": ("Batman 001.torrent", b"torrent-bytes", "application/x-bittorrent")
        }


@pytest.mark.asyncio
class TestDownloadStatus:
    """Tests for qBittorrent status and queue mapping."""

    async def test_get_download_status_maps_stalled_torrent(self) -> None:
        client = _make_client()
        client._request = AsyncMock(  # type: ignore[method-assign]
            return_value=_make_response(
                json_data=[
                    {
                        "hash": "hash-1",
                        "name": "Batman 001",
                        "state": "stalledDL",
                        "progress": 0.42,
                        "total_size": 123_456,
                        "dlspeed": 9000,
                        "eta": 8640000,
                        "content_path": "/downloads/Batman 001.cbz",
                    }
                ]
            )
        )

        status = await client.get_download_status("hash-1")

        assert status.external_id == "hash-1"
        assert status.title == "Batman 001"
        assert status.state == "downloading"
        assert status.progress == pytest.approx(0.42)
        assert status.size_bytes == 123_456
        assert status.speed_bytes == 0
        assert status.eta_seconds is None
        assert status.downloaded_path == "/downloads/Batman 001.cbz"
        assert status.client_state == "Stalled"

    async def test_get_download_status_raises_when_torrent_is_missing(self) -> None:
        client = _make_client()
        client._request = AsyncMock(  # type: ignore[method-assign]
            return_value=_make_response(json_data=[])
        )

        with pytest.raises(QBittorrentError, match="Torrent not found: missing"):
            await client.get_download_status("missing")

    async def test_get_queue_maps_all_torrents(self) -> None:
        client = _make_client()
        client._request = AsyncMock(  # type: ignore[method-assign]
            return_value=_make_response(
                json_data=[
                    {"hash": "hash-1", "name": "Batman 001", "state": "queuedDL"},
                    {"hash": "hash-2", "name": "Batman 002", "state": "uploading"},
                ]
            )
        )

        queue = await client.get_queue()

        assert [(item.external_id, item.state) for item in queue] == [
            ("hash-1", "queued"),
            ("hash-2", "completed"),
        ]
        client._request.assert_awaited_once_with(  # type: ignore[attr-defined]
            "GET",
            "/torrents/info",
            params={"filter": "all"},
        )


@pytest.mark.asyncio
class TestRemoveDownload:
    """Tests for qBittorrent removal behavior."""

    async def test_remove_download_sends_delete_files_flag(self) -> None:
        client = _make_client()
        client._request = AsyncMock(return_value=_make_response(text="Ok."))  # type: ignore[method-assign]

        result = await client.remove_download("hash-1", delete_files=True)

        assert result is True
        client._request.assert_awaited_once_with(  # type: ignore[attr-defined]
            "POST",
            "/torrents/delete",
            data={"hashes": "hash-1", "deleteFiles": "true"},
        )

    async def test_remove_download_returns_false_when_client_errors(self) -> None:
        client = _make_client()
        client._request = AsyncMock(side_effect=QBittorrentError("boom"))  # type: ignore[method-assign]

        result = await client.remove_download("hash-1", delete_files=False)

        assert result is False


@pytest.mark.asyncio
class TestHealthAndOptions:
    """Tests for qBittorrent health and options lookup."""

    async def test_test_connection_returns_version_details(self) -> None:
        client = _make_client()
        client._request = AsyncMock(return_value=_make_response(text="v5.0.3"))  # type: ignore[method-assign]

        health = await client.test_connection()

        assert health.healthy is True
        assert health.message == "qBittorrent v5.0.3"
        assert health.details == {"version": "v5.0.3"}

    async def test_test_connection_reports_provider_error(self) -> None:
        client = _make_client()
        client._request = AsyncMock(side_effect=QBittorrentError("auth failed"))  # type: ignore[method-assign]

        health = await client.test_connection()

        assert health.healthy is False
        assert health.message == "qBittorrent error: auth failed"

    async def test_get_options_sorts_categories_and_returns_save_paths(self) -> None:
        client = _make_client()
        client._request = AsyncMock(  # type: ignore[method-assign]
            return_value=_make_response(
                json_data={
                    "zines": {"savePath": "/downloads/zines"},
                    "comics": {"savePath": "/downloads/comics"},
                    "empty": {"savePath": ""},
                }
            )
        )

        options = await client.get_options()

        assert options.categories == ["comics", "empty", "zines"]
        assert options.download_directories == ["/downloads/zines", "/downloads/comics"]
