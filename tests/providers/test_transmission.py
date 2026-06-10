"""Tests for Transmission download client implementation (DCE-C.2).

Covers session ID negotiation, add_torrent, get_download_status, get_queue,
remove_download, test_connection, status mapping, and edge cases.

Run:
    pytest tests/providers/test_transmission.py -v
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pullbox.providers.download.transmission import (
    TransmissionClient,
    TransmissionError,
    _map_transmission_status,
)

# Fake .torrent content for mocking httpx downloads
_FAKE_TORRENT_CONTENT = b"d8:announce0:4:infod4:name4:test12:piece lengthi262144e6:pieces0:ee"


def _make_client(**kwargs: Any) -> TransmissionClient:
    """Create a Transmission client with defaults."""
    defaults: dict[str, Any] = {
        "url": "http://localhost:9091",
        "username": "admin",
        "password": "secret",
    }
    defaults.update(kwargs)
    return TransmissionClient(**defaults)


def _mock_httpx_for_torrent() -> MagicMock:
    """Create a mock httpx.AsyncClient context manager that returns .torrent content."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = _FAKE_TORRENT_CONTENT
    mock_response.headers = {"content-type": "application/x-bittorrent"}
    mock_response.raise_for_status = MagicMock()

    mock_http = AsyncMock()
    mock_http.get = AsyncMock(return_value=mock_response)
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    return mock_http


def _make_response(
    status_code: int = 200,
    json_data: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> MagicMock:
    """Create a mock httpx response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.headers = headers or {}
    resp.raise_for_status = MagicMock()
    return resp


# ── Session ID negotiation ───────────────────────────────────────


@pytest.mark.asyncio
class TestSessionNegotiation:
    """Tests for Transmission's 409 session-id CSRF negotiation."""

    async def test_first_request_409_then_retry_succeeds(self) -> None:
        """First RPC call gets 409, extracts session ID, retries successfully."""
        client = _make_client()

        call_count = 0

        async def mock_post(*args: Any, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_response(
                    status_code=409,
                    headers={"X-Transmission-Session-Id": "test-session-123"},
                )
            return _make_response(
                json_data={"result": "success", "arguments": {"version": "4.0.0"}},
            )

        client._client.post = mock_post  # type: ignore[assignment]
        result = await client._rpc("session-get")

        assert result == {"version": "4.0.0"}
        assert call_count == 2

    async def test_session_id_refresh_on_409_during_operation(self) -> None:
        """409 during normal operation triggers session refresh and retry."""
        client = _make_client()
        client._session_id = "old-session"

        call_count = 0

        async def mock_post(*args: Any, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_response(
                    status_code=409,
                    headers={"X-Transmission-Session-Id": "new-session-456"},
                )
            return _make_response(
                json_data={"result": "success", "arguments": {}},
            )

        client._client.post = mock_post  # type: ignore[assignment]
        await client._rpc("torrent-get", {"ids": [1]})

        assert client._session_id == "new-session-456"


# ── add_torrent ──────────────────────────────────────────────────


@pytest.mark.asyncio
class TestAddTorrent:
    """Tests for TransmissionClient.add_torrent()."""

    async def test_add_magnet_returns_hash(self) -> None:
        client = _make_client()
        mock_rpc = AsyncMock()
        mock_rpc.return_value = {
            "torrent-added": {"hashString": "abc123def456", "name": "Test"},
        }
        client._rpc = mock_rpc
        result = await client.add_torrent("magnet:?xt=urn:btih:abc123def456", "Test Torrent")

        assert result == "abc123def456"

    async def test_add_torrent_url_returns_hash(self) -> None:
        client = _make_client()
        mock_rpc = AsyncMock()
        mock_rpc.return_value = {
            "torrent-added": {"hashString": "xyz789", "name": "Test"},
        }
        client._rpc = mock_rpc
        with patch("httpx.AsyncClient", return_value=_mock_httpx_for_torrent()):
            result = await client.add_torrent("http://example.com/test.torrent", "Test Torrent")

        assert result == "xyz789"

    async def test_add_duplicate_returns_existing_hash(self) -> None:
        """Transmission returns torrent-duplicate for existing torrents."""
        client = _make_client()
        mock_rpc = AsyncMock()
        mock_rpc.return_value = {
            "torrent-duplicate": {"hashString": "existing123", "name": "Test"},
        }
        client._rpc = mock_rpc
        result = await client.add_torrent("magnet:?xt=urn:btih:existing123", "Test")

        assert result == "existing123"

    async def test_add_torrent_with_download_dir(self) -> None:
        client = _make_client(download_dir="/mnt/comics")
        mock_rpc = AsyncMock()
        mock_rpc.return_value = {
            "torrent-added": {"hashString": "aaa", "name": "Test"},
        }
        client._rpc = mock_rpc
        with patch("httpx.AsyncClient", return_value=_mock_httpx_for_torrent()):
            await client.add_torrent("http://example.com/test.torrent", "Test")

        call_args = mock_rpc.call_args[0][1]
        assert call_args["download-dir"] == "/mnt/comics"

    async def test_add_torrent_with_bandwidth_priority(self) -> None:
        client = _make_client(bandwidth_priority=1)
        mock_rpc = AsyncMock()
        mock_rpc.return_value = {
            "torrent-added": {"hashString": "bbb", "name": "Test"},
        }
        client._rpc = mock_rpc
        with patch("httpx.AsyncClient", return_value=_mock_httpx_for_torrent()):
            await client.add_torrent("http://example.com/test.torrent", "Test")

        call_args = mock_rpc.call_args[0][1]
        assert call_args["bandwidthPriority"] == 1

    async def test_add_torrent_normalizes_hash_to_lowercase(self) -> None:
        """Some Transmission versions return uppercase hashes."""
        client = _make_client()
        mock_rpc = AsyncMock()
        mock_rpc.return_value = {
            "torrent-added": {"hashString": "ABC123DEF456", "name": "Test"},
        }
        client._rpc = mock_rpc
        with patch("httpx.AsyncClient", return_value=_mock_httpx_for_torrent()):
            result = await client.add_torrent("http://example.com/t.torrent", "Test")

        assert result == "abc123def456"

    async def test_add_torrent_no_hash_in_response_raises(self) -> None:
        """Missing hashString in response raises error."""
        client = _make_client()
        mock_rpc = AsyncMock()
        mock_rpc.return_value = {}
        client._rpc = mock_rpc
        with (
            patch("httpx.AsyncClient", return_value=_mock_httpx_for_torrent()),
            pytest.raises(TransmissionError, match="No torrent hash"),
        ):
            await client.add_torrent("http://example.com/t.torrent", "Test")


# ── add_nzb ──────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestAddNzb:
    """Verify add_nzb raises NotImplementedError."""

    async def test_add_nzb_raises(self) -> None:
        client = _make_client()
        with pytest.raises(NotImplementedError, match="does not support NZB"):
            await client.add_nzb("http://example.com/test.nzb", "Test")


# ── get_download_status ──────────────────────────────────────────


@pytest.mark.asyncio
class TestGetDownloadStatus:
    """Tests for TransmissionClient.get_download_status()."""

    async def test_active_torrent(self) -> None:
        client = _make_client()
        mock_rpc = AsyncMock()
        mock_rpc.return_value = {
            "torrents": [
                {
                    "hashString": "abc123",
                    "name": "Batman 001",
                    "status": 4,
                    "percentDone": 0.65,
                    "totalSize": 157286400,
                    "rateDownload": 1048576,
                    "eta": 120,
                    "downloadDir": "/downloads/",
                    "error": 0,
                    "errorString": "",
                }
            ],
        }
        client._rpc = mock_rpc
        status = await client.get_download_status("abc123")

        assert status.external_id == "abc123"
        assert status.title == "Batman 001"
        assert status.state == "downloading"
        assert status.progress == pytest.approx(0.65)
        assert status.size_bytes == 157286400
        assert status.speed_bytes == 1048576
        assert status.eta_seconds == 120

    async def test_completed_seeding(self) -> None:
        client = _make_client()
        mock_rpc = AsyncMock()
        mock_rpc.return_value = {
            "torrents": [
                {
                    "hashString": "def456",
                    "name": "Batman 002",
                    "status": 6,
                    "percentDone": 1.0,
                    "totalSize": 100000000,
                    "rateDownload": 0,
                    "eta": -2,
                    "downloadDir": "/downloads/complete/",
                    "error": 0,
                    "errorString": "",
                }
            ],
        }
        client._rpc = mock_rpc
        status = await client.get_download_status("def456")

        assert status.state == "completed"
        assert status.progress == 1.0
        assert status.eta_seconds is None

    async def test_not_found_raises(self) -> None:
        client = _make_client()
        mock_rpc = AsyncMock()
        mock_rpc.return_value = {"torrents": []}
        client._rpc = mock_rpc
        with pytest.raises(TransmissionError, match="not found"):
            await client.get_download_status("missing123")

    async def test_torrent_with_error(self) -> None:
        """error=3 (local error) → state=failed with errorString."""
        client = _make_client()
        mock_rpc = AsyncMock()
        mock_rpc.return_value = {
            "torrents": [
                {
                    "hashString": "err123",
                    "name": "Broken",
                    "status": 0,
                    "percentDone": 0.3,
                    "totalSize": 50000000,
                    "rateDownload": 0,
                    "eta": -1,
                    "downloadDir": "/downloads/",
                    "error": 3,
                    "errorString": "No space left on device",
                }
            ],
        }
        client._rpc = mock_rpc
        status = await client.get_download_status("err123")

        assert status.state == "failed"
        assert status.error_message == "No space left on device"

    async def test_eta_negative_one_is_none(self) -> None:
        """eta=-1 (unknown) → eta_seconds=None."""
        client = _make_client()
        mock_rpc = AsyncMock()
        mock_rpc.return_value = {
            "torrents": [
                {
                    "hashString": "eta1",
                    "name": "Test",
                    "status": 4,
                    "percentDone": 0.1,
                    "totalSize": 100,
                    "rateDownload": 0,
                    "eta": -1,
                    "downloadDir": "/dl/",
                    "error": 0,
                    "errorString": "",
                }
            ],
        }
        client._rpc = mock_rpc
        status = await client.get_download_status("eta1")

        assert status.eta_seconds is None

    async def test_eta_negative_two_is_none(self) -> None:
        """eta=-2 (not applicable) → eta_seconds=None."""
        client = _make_client()
        mock_rpc = AsyncMock()
        mock_rpc.return_value = {
            "torrents": [
                {
                    "hashString": "eta2",
                    "name": "Test",
                    "status": 6,
                    "percentDone": 1.0,
                    "totalSize": 100,
                    "rateDownload": 0,
                    "eta": -2,
                    "downloadDir": "/dl/",
                    "error": 0,
                    "errorString": "",
                }
            ],
        }
        client._rpc = mock_rpc
        status = await client.get_download_status("eta2")

        assert status.eta_seconds is None

    async def test_stalled_download(self) -> None:
        """rateDownload=0 while status=4 → client_state='Stalled'."""
        client = _make_client()
        mock_rpc = AsyncMock()
        mock_rpc.return_value = {
            "torrents": [
                {
                    "hashString": "stall1",
                    "name": "Test",
                    "status": 4,
                    "percentDone": 0.5,
                    "totalSize": 1000,
                    "rateDownload": 0,
                    "eta": -1,
                    "downloadDir": "/dl/",
                    "error": 0,
                    "errorString": "",
                }
            ],
        }
        client._rpc = mock_rpc
        status = await client.get_download_status("stall1")

        assert status.state == "downloading"
        assert status.client_state == "Stalled"


# ── get_queue ────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestGetQueue:
    """Tests for TransmissionClient.get_queue()."""

    async def test_mixed_states(self) -> None:
        client = _make_client()
        mock_rpc = AsyncMock()
        mock_rpc.return_value = {
            "torrents": [
                {
                    "hashString": "a",
                    "name": "DL",
                    "status": 4,
                    "percentDone": 0.5,
                    "totalSize": 100,
                    "rateDownload": 1000,
                    "eta": 60,
                    "downloadDir": "/dl/",
                    "error": 0,
                    "errorString": "",
                },
                {
                    "hashString": "b",
                    "name": "Seed",
                    "status": 6,
                    "percentDone": 1.0,
                    "totalSize": 200,
                    "rateDownload": 0,
                    "eta": -2,
                    "downloadDir": "/dl/",
                    "error": 0,
                    "errorString": "",
                },
                {
                    "hashString": "c",
                    "name": "Paused",
                    "status": 0,
                    "percentDone": 0.2,
                    "totalSize": 300,
                    "rateDownload": 0,
                    "eta": -1,
                    "downloadDir": "/dl/",
                    "error": 0,
                    "errorString": "",
                },
            ],
        }
        client._rpc = mock_rpc
        result = await client.get_queue()

        assert len(result) == 3
        assert result[0].state == "downloading"
        assert result[1].state == "completed"
        assert result[2].state == "paused"

    async def test_empty_queue(self) -> None:
        client = _make_client()
        mock_rpc = AsyncMock()
        mock_rpc.return_value = {"torrents": []}
        client._rpc = mock_rpc
        result = await client.get_queue()

        assert result == []


# ── remove_download ──────────────────────────────────────────────


@pytest.mark.asyncio
class TestRemoveDownload:
    """Tests for TransmissionClient.remove_download()."""

    async def test_remove_without_files(self) -> None:
        client = _make_client()
        mock_rpc = AsyncMock()
        mock_rpc.return_value = {}
        client._rpc = mock_rpc
        result = await client.remove_download("abc123")

        assert result is True
        call_args = mock_rpc.call_args[0][1]
        assert call_args["delete-local-data"] is False

    async def test_remove_with_files(self) -> None:
        client = _make_client()
        mock_rpc = AsyncMock()
        mock_rpc.return_value = {}
        client._rpc = mock_rpc
        result = await client.remove_download("abc123", delete_files=True)

        assert result is True
        call_args = mock_rpc.call_args[0][1]
        assert call_args["delete-local-data"] is True

    async def test_remove_failure(self) -> None:
        client = _make_client()
        mock_rpc = AsyncMock()
        mock_rpc.side_effect = TransmissionError("not found")
        client._rpc = mock_rpc
        result = await client.remove_download("missing")

        assert result is False


# ── test_connection ──────────────────────────────────────────────


@pytest.mark.asyncio
class TestTestConnection:
    """Tests for TransmissionClient.test_connection()."""

    async def test_healthy(self) -> None:
        client = _make_client()
        mock_rpc = AsyncMock()
        mock_rpc.return_value = {"version": "4.0.0", "rpc-version": 18}
        client._rpc = mock_rpc
        result = await client.test_connection()

        assert result.healthy is True
        assert "4.0.0" in result.message

    async def test_connection_refused(self) -> None:
        client = _make_client()
        mock_rpc = AsyncMock()
        mock_rpc.side_effect = TransmissionError("Connection refused")
        client._rpc = mock_rpc
        result = await client.test_connection()

        assert result.healthy is False

    async def test_unexpected_error(self) -> None:
        client = _make_client()
        mock_rpc = AsyncMock()
        mock_rpc.side_effect = RuntimeError("boom")
        client._rpc = mock_rpc
        result = await client.test_connection()

        assert result.healthy is False


# ── Status mapping ───────────────────────────────────────────────


class TestStatusMapping:
    """Tests for _map_transmission_status — all 7 status codes."""

    def test_stopped(self) -> None:
        assert _map_transmission_status(0) == "paused"

    def test_check_pending(self) -> None:
        assert _map_transmission_status(1) == "queued"

    def test_checking(self) -> None:
        assert _map_transmission_status(2) == "downloading"

    def test_download_pending(self) -> None:
        assert _map_transmission_status(3) == "queued"

    def test_downloading(self) -> None:
        assert _map_transmission_status(4) == "downloading"

    def test_seed_pending(self) -> None:
        assert _map_transmission_status(5) == "completed"

    def test_seeding(self) -> None:
        assert _map_transmission_status(6) == "completed"

    def test_unknown_status(self) -> None:
        assert _map_transmission_status(99) == "queued"


class TestClientStateMapping:
    """Tests for human-readable client_state values."""

    async def _get_status_with_state(
        self,
        status_code: int,
        rate: int = 1000,
    ) -> Any:
        client = _make_client()
        mock_rpc = AsyncMock()
        mock_rpc.return_value = {
            "torrents": [
                {
                    "hashString": "x",
                    "name": "T",
                    "status": status_code,
                    "percentDone": 0.5,
                    "totalSize": 100,
                    "rateDownload": rate,
                    "eta": -1,
                    "downloadDir": "/dl/",
                    "error": 0,
                    "errorString": "",
                }
            ],
        }
        client._rpc = mock_rpc
        return await client.get_download_status("x")

    @pytest.mark.asyncio
    async def test_checking_has_client_state(self) -> None:
        status = await self._get_status_with_state(2)
        assert status.client_state == "Checking"

    @pytest.mark.asyncio
    async def test_normal_downloading_no_client_state(self) -> None:
        status = await self._get_status_with_state(4, rate=5000)
        assert status.client_state is None


# ── Properties ───────────────────────────────────────────────────


class TestProperties:
    """Tests for TransmissionClient properties."""

    def test_name(self) -> None:
        assert _make_client().name == "transmission"

    def test_client_type(self) -> None:
        assert _make_client().client_type == "transmission"


# ── Auth edge cases ──────────────────────────────────────────────


@pytest.mark.asyncio
class TestAuthEdgeCases:
    """Authentication edge cases."""

    async def test_auth_failure_401(self) -> None:
        """Wrong credentials → 401 → TransmissionError."""
        client = _make_client()

        async def mock_post(*args: Any, **kwargs: Any) -> MagicMock:
            return _make_response(status_code=401)

        client._client.post = mock_post  # type: ignore[assignment]
        with pytest.raises(TransmissionError, match=r"[Aa]uthentication"):
            await client._rpc("session-get")

    async def test_no_auth_still_needs_session_id(self) -> None:
        """Transmission without auth still requires session ID negotiation."""
        client = _make_client(username="", password="")
        call_count = 0

        async def mock_post(*args: Any, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_response(
                    status_code=409,
                    headers={"X-Transmission-Session-Id": "no-auth-session"},
                )
            return _make_response(
                json_data={"result": "success", "arguments": {"version": "4.0"}},
            )

        client._client.post = mock_post  # type: ignore[assignment]
        result = await client._rpc("session-get")
        assert result == {"version": "4.0"}
