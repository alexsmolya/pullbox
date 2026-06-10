"""Tests for Deluge download client implementation (DCE-C.3).

Covers authentication, add_torrent, get_download_status, get_queue,
remove_download, test_connection, label handling, status mapping,
and edge cases.

Run:
    pytest tests/providers/test_deluge.py -v
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pullbox.providers.download.deluge import (
    DelugeClient,
    DelugeError,
    _map_deluge_state,
)

# Fake .torrent content for mocking httpx downloads
_FAKE_TORRENT_CONTENT = b"d8:announce0:4:infod4:name4:test12:piece lengthi262144e6:pieces0:ee"


def _make_client(**kwargs: Any) -> DelugeClient:
    """Create a Deluge client with defaults."""
    defaults: dict[str, Any] = {
        "url": "http://localhost:8112",
        "password": "deluge",
    }
    defaults.update(kwargs)
    return DelugeClient(**defaults)


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
) -> MagicMock:
    """Create a mock httpx response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    return resp


# ── Authentication ───────────────────────────────────────────────


@pytest.mark.asyncio
class TestAuthentication:
    """Tests for Deluge auth.login flow."""

    async def test_login_success(self) -> None:
        client = _make_client()
        mock_rpc = AsyncMock()
        # auth.login returns True on success
        mock_rpc.return_value = True
        client._rpc_raw = mock_rpc  # type: ignore[attr-defined]
        # Direct login call
        client._authenticated = False

        async def fake_rpc(method: str, params: list[Any] | None = None) -> Any:
            if method == "auth.login":
                return True
            if method == "web.connected":
                return True  # Skip daemon connect
            return None

        client._rpc_raw = AsyncMock(side_effect=fake_rpc)  # type: ignore[attr-defined]
        await client._login()
        assert client._authenticated is True

    async def test_login_failure_raises(self) -> None:
        client = _make_client()

        async def fake_rpc(method: str, params: list[Any] | None = None) -> Any:
            if method == "auth.login":
                return False
            return None

        client._rpc_raw = AsyncMock(side_effect=fake_rpc)  # type: ignore[attr-defined]
        with pytest.raises(DelugeError, match=r"[Aa]uthentication"):
            await client._login()

    async def test_session_expiry_triggers_relogin(self) -> None:
        """Auth expiry during operation → re-login and retry once."""
        client = _make_client()
        client._authenticated = True

        call_count = 0

        async def fake_rpc_raw(method: str, params: list[Any] | None = None) -> Any:
            nonlocal call_count
            call_count += 1
            if method == "auth.login":
                return True
            if method == "web.connected":
                return True
            if method == "daemon.get_version":
                if call_count <= 2:
                    # Simulate auth expiry on first attempt
                    raise DelugeError("Not authenticated")
                return "2.1.1"
            return None

        client._rpc_raw = AsyncMock(side_effect=fake_rpc_raw)  # type: ignore[attr-defined]
        result = await client._rpc("daemon.get_version")
        assert result == "2.1.1"

    async def test_login_null_result_treated_as_success(self) -> None:
        """Deluge < 2.0 may return null instead of true — treat as success if no error."""
        client = _make_client()

        async def fake_rpc(method: str, params: list[Any] | None = None) -> Any:
            if method == "auth.login":
                return None  # null/None instead of True
            if method == "web.connected":
                return True
            return None

        client._rpc_raw = AsyncMock(side_effect=fake_rpc)  # type: ignore[attr-defined]
        # Should not raise — None without error means success
        await client._login()
        assert client._authenticated is True


# ── add_torrent ──────────────────────────────────────────────────


@pytest.mark.asyncio
class TestAddTorrent:
    """Tests for DelugeClient.add_torrent()."""

    async def test_add_magnet_returns_hash(self) -> None:
        client = _make_client()
        client._authenticated = True
        mock_rpc = AsyncMock()
        mock_rpc.return_value = "abc123def456789"
        client._rpc = mock_rpc  # type: ignore[assignment]
        result = await client.add_torrent(
            "magnet:?xt=urn:btih:abc123def456789",
            "Test Torrent",
        )

        assert result == "abc123def456789"
        call_args = mock_rpc.call_args_list[0]
        assert call_args[0][0] == "core.add_torrent_magnet"

    async def test_add_url_returns_hash(self) -> None:
        client = _make_client()
        client._authenticated = True
        mock_rpc = AsyncMock()
        mock_rpc.return_value = "xyz789hash"
        client._rpc = mock_rpc  # type: ignore[assignment]
        with patch("httpx.AsyncClient", return_value=_mock_httpx_for_torrent()):
            result = await client.add_torrent(
                "http://example.com/test.torrent",
                "Test Torrent",
            )

        assert result == "xyz789hash"
        call_args = mock_rpc.call_args_list[0]
        assert call_args[0][0] == "core.add_torrent_file"

    async def test_add_torrent_with_label(self) -> None:
        """Label is set via label.set_torrent after add."""
        client = _make_client(label="comics")
        client._authenticated = True
        call_log: list[tuple[str, list[Any] | None]] = []

        async def fake_rpc(method: str, params: list[Any] | None = None) -> Any:
            call_log.append((method, params))
            if method == "core.add_torrent_file":
                return "hash123"
            if method == "label.get_labels":
                return ["comics"]
            if method == "label.set_torrent":
                return None
            return None

        client._rpc = AsyncMock(side_effect=fake_rpc)  # type: ignore[assignment]
        with patch("httpx.AsyncClient", return_value=_mock_httpx_for_torrent()):
            result = await client.add_torrent(
                "http://example.com/t.torrent",
                "Test",
            )

        assert result == "hash123"
        methods_called = [c[0] for c in call_log]
        assert "label.set_torrent" in methods_called

    async def test_add_torrent_label_auto_created(self) -> None:
        """If label doesn't exist, create it before setting."""
        client = _make_client(label="newlabel")
        client._authenticated = True
        call_log: list[str] = []

        async def fake_rpc(method: str, params: list[Any] | None = None) -> Any:
            call_log.append(method)
            if method == "core.add_torrent_file":
                return "hash456"
            if method == "label.get_labels":
                return ["existing"]  # "newlabel" not in list
            if method == "label.add":
                return None
            if method == "label.set_torrent":
                return None
            return None

        client._rpc = AsyncMock(side_effect=fake_rpc)  # type: ignore[assignment]
        with patch("httpx.AsyncClient", return_value=_mock_httpx_for_torrent()):
            await client.add_torrent("http://example.com/t.torrent", "Test")

        assert "label.add" in call_log
        assert "label.set_torrent" in call_log

    async def test_add_torrent_label_plugin_unavailable(self) -> None:
        """Label plugin not enabled → warning logged, no error."""
        client = _make_client(label="comics")
        client._authenticated = True

        async def fake_rpc(method: str, params: list[Any] | None = None) -> Any:
            if method == "core.add_torrent_file":
                return "hash789"
            if method == "label.get_labels":
                raise DelugeError("Unknown method")
            return None

        client._rpc = AsyncMock(side_effect=fake_rpc)  # type: ignore[assignment]
        # Should not raise despite label plugin failure
        with patch("httpx.AsyncClient", return_value=_mock_httpx_for_torrent()):
            result = await client.add_torrent("http://example.com/t.torrent", "Test")
        assert result == "hash789"

    async def test_add_torrent_returns_none_duplicate(self) -> None:
        """Deluge 2.x returns None for duplicate torrents."""
        client = _make_client()
        client._authenticated = True

        call_count = 0

        async def fake_rpc(method: str, params: list[Any] | None = None) -> Any:
            nonlocal call_count
            call_count += 1
            if method == "core.add_torrent_magnet":
                return None  # Duplicate
            return None

        client._rpc = AsyncMock(side_effect=fake_rpc)  # type: ignore[assignment]
        with pytest.raises(DelugeError, match=r"[Ff]ailed|[Nn]o hash|[Dd]uplicate"):
            await client.add_torrent("magnet:?xt=urn:btih:abc", "Test")

    async def test_add_torrent_with_move_completed(self) -> None:
        client = _make_client(move_completed_path="/mnt/complete")
        client._authenticated = True
        mock_rpc = AsyncMock()
        mock_rpc.return_value = "hash999"
        client._rpc = mock_rpc  # type: ignore[assignment]
        with patch("httpx.AsyncClient", return_value=_mock_httpx_for_torrent()):
            await client.add_torrent("http://example.com/t.torrent", "Test")

        call_args = mock_rpc.call_args_list[0]
        # core.add_torrent_file params: [filename, filedump, options]
        options = call_args[0][1][2]  # third param is options dict
        assert options["move_completed"] is True
        assert options["move_completed_path"] == "/mnt/complete"


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
    """Tests for DelugeClient.get_download_status()."""

    async def test_downloading_torrent(self) -> None:
        client = _make_client()
        client._authenticated = True
        mock_rpc = AsyncMock()
        mock_rpc.return_value = {
            "name": "Batman 001",
            "state": "Downloading",
            "progress": 65.0,
            "total_size": 157286400,
            "download_payload_rate": 1048576,
            "eta": 120.0,
            "save_path": "/downloads/",
            "message": "",
            "tracker_status": "OK",
        }
        client._rpc = mock_rpc  # type: ignore[assignment]
        status = await client.get_download_status("abc123")

        assert status.external_id == "abc123"
        assert status.title == "Batman 001"
        assert status.state == "downloading"
        assert status.progress == pytest.approx(0.65)
        assert status.size_bytes == 157286400
        assert status.speed_bytes == 1048576
        assert status.eta_seconds == 120

    async def test_seeding_torrent(self) -> None:
        client = _make_client()
        client._authenticated = True
        mock_rpc = AsyncMock()
        mock_rpc.return_value = {
            "name": "Batman 002",
            "state": "Seeding",
            "progress": 100.0,
            "total_size": 100000000,
            "download_payload_rate": 0,
            "eta": 0.0,
            "save_path": "/downloads/complete/",
            "message": "",
            "tracker_status": "",
        }
        client._rpc = mock_rpc  # type: ignore[assignment]
        status = await client.get_download_status("def456")

        assert status.state == "completed"
        assert status.progress == 1.0
        assert status.eta_seconds is None

    async def test_error_state(self) -> None:
        client = _make_client()
        client._authenticated = True
        mock_rpc = AsyncMock()
        mock_rpc.return_value = {
            "name": "Broken",
            "state": "Error",
            "progress": 30.0,
            "total_size": 50000000,
            "download_payload_rate": 0,
            "eta": 0.0,
            "save_path": "/downloads/",
            "message": "Disk full",
            "tracker_status": "",
        }
        client._rpc = mock_rpc  # type: ignore[assignment]
        status = await client.get_download_status("err123")

        assert status.state == "failed"
        assert status.error_message == "Disk full"

    async def test_not_found_raises(self) -> None:
        client = _make_client()
        client._authenticated = True
        mock_rpc = AsyncMock()
        mock_rpc.side_effect = DelugeError("Unknown torrent")
        client._rpc = mock_rpc  # type: ignore[assignment]
        with pytest.raises(DelugeError):
            await client.get_download_status("missing")

    async def test_progress_divided_by_100(self) -> None:
        """Deluge progress is 0-100, we normalize to 0.0-1.0."""
        client = _make_client()
        client._authenticated = True
        mock_rpc = AsyncMock()
        mock_rpc.return_value = {
            "name": "Test",
            "state": "Downloading",
            "progress": 42.5,
            "total_size": 100,
            "download_payload_rate": 0,
            "eta": 0.0,
            "save_path": "/dl/",
            "message": "",
            "tracker_status": "",
        }
        client._rpc = mock_rpc  # type: ignore[assignment]
        status = await client.get_download_status("x")

        assert status.progress == pytest.approx(0.425)

    async def test_eta_zero_seeding_is_none(self) -> None:
        """eta=0 when seeding → eta_seconds=None."""
        client = _make_client()
        client._authenticated = True
        mock_rpc = AsyncMock()
        mock_rpc.return_value = {
            "name": "Test",
            "state": "Seeding",
            "progress": 100.0,
            "total_size": 100,
            "download_payload_rate": 0,
            "eta": 0.0,
            "save_path": "/dl/",
            "message": "",
            "tracker_status": "",
        }
        client._rpc = mock_rpc  # type: ignore[assignment]
        status = await client.get_download_status("y")

        assert status.eta_seconds is None

    async def test_eta_negative_is_none(self) -> None:
        """eta=-1 (unknown) → eta_seconds=None."""
        client = _make_client()
        client._authenticated = True
        mock_rpc = AsyncMock()
        mock_rpc.return_value = {
            "name": "Test",
            "state": "Downloading",
            "progress": 50.0,
            "total_size": 100,
            "download_payload_rate": 0,
            "eta": -1.0,
            "save_path": "/dl/",
            "message": "",
            "tracker_status": "",
        }
        client._rpc = mock_rpc  # type: ignore[assignment]
        status = await client.get_download_status("z")

        assert status.eta_seconds is None


# ── get_queue ────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestGetQueue:
    """Tests for DelugeClient.get_queue()."""

    async def test_multiple_torrents(self) -> None:
        client = _make_client()
        client._authenticated = True
        mock_rpc = AsyncMock()
        mock_rpc.return_value = {
            "hash1": {
                "name": "DL",
                "state": "Downloading",
                "progress": 50.0,
                "total_size": 100,
                "download_payload_rate": 1000,
                "eta": 60.0,
                "save_path": "/dl/",
                "message": "",
                "tracker_status": "",
            },
            "hash2": {
                "name": "Done",
                "state": "Seeding",
                "progress": 100.0,
                "total_size": 200,
                "download_payload_rate": 0,
                "eta": 0.0,
                "save_path": "/dl/",
                "message": "",
                "tracker_status": "",
            },
        }
        client._rpc = mock_rpc  # type: ignore[assignment]
        result = await client.get_queue()

        assert len(result) == 2
        states = {r.state for r in result}
        assert "downloading" in states
        assert "completed" in states

    async def test_empty_queue(self) -> None:
        client = _make_client()
        client._authenticated = True
        mock_rpc = AsyncMock()
        mock_rpc.return_value = {}
        client._rpc = mock_rpc  # type: ignore[assignment]
        result = await client.get_queue()

        assert result == []


# ── remove_download ──────────────────────────────────────────────


@pytest.mark.asyncio
class TestRemoveDownload:
    """Tests for DelugeClient.remove_download()."""

    async def test_remove_without_files(self) -> None:
        client = _make_client()
        client._authenticated = True
        mock_rpc = AsyncMock()
        mock_rpc.return_value = True
        client._rpc = mock_rpc  # type: ignore[assignment]
        result = await client.remove_download("abc123")

        assert result is True
        call_args = mock_rpc.call_args[0]
        assert call_args[1] == ["abc123", False]

    async def test_remove_with_files(self) -> None:
        client = _make_client()
        client._authenticated = True
        mock_rpc = AsyncMock()
        mock_rpc.return_value = True
        client._rpc = mock_rpc  # type: ignore[assignment]
        result = await client.remove_download("abc123", delete_files=True)

        assert result is True
        call_args = mock_rpc.call_args[0]
        assert call_args[1] == ["abc123", True]

    async def test_remove_failure(self) -> None:
        client = _make_client()
        client._authenticated = True
        mock_rpc = AsyncMock()
        mock_rpc.side_effect = DelugeError("not found")
        client._rpc = mock_rpc  # type: ignore[assignment]
        result = await client.remove_download("missing")

        assert result is False


# ── test_connection ──────────────────────────────────────────────


@pytest.mark.asyncio
class TestTestConnection:
    """Tests for DelugeClient.test_connection()."""

    async def test_healthy(self) -> None:
        client = _make_client()
        client._authenticated = True
        mock_rpc = AsyncMock()
        mock_rpc.return_value = "2.1.1"
        client._rpc = mock_rpc  # type: ignore[assignment]
        result = await client.test_connection()

        assert result.healthy is True
        assert "2.1.1" in result.message

    async def test_connection_refused(self) -> None:
        client = _make_client()
        client._authenticated = True
        mock_rpc = AsyncMock()
        mock_rpc.side_effect = DelugeError("Connection refused")
        client._rpc = mock_rpc  # type: ignore[assignment]
        result = await client.test_connection()

        assert result.healthy is False

    async def test_not_connected_daemon(self) -> None:
        """Daemon not connected to Web UI → helpful error message."""
        client = _make_client()
        client._authenticated = True
        mock_rpc = AsyncMock()
        mock_rpc.side_effect = DelugeError("Not Connected")
        client._rpc = mock_rpc  # type: ignore[assignment]
        result = await client.test_connection()

        assert result.healthy is False
        assert "Not Connected" in result.message


# ── Status mapping ───────────────────────────────────────────────


class TestStatusMapping:
    """Tests for _map_deluge_state — all Deluge states."""

    def test_downloading(self) -> None:
        assert _map_deluge_state("Downloading") == "downloading"

    def test_seeding(self) -> None:
        assert _map_deluge_state("Seeding") == "completed"

    def test_paused(self) -> None:
        assert _map_deluge_state("Paused") == "paused"

    def test_checking(self) -> None:
        assert _map_deluge_state("Checking") == "downloading"

    def test_queued(self) -> None:
        assert _map_deluge_state("Queued") == "queued"

    def test_error(self) -> None:
        assert _map_deluge_state("Error") == "failed"

    def test_moving(self) -> None:
        assert _map_deluge_state("Moving") == "downloading"

    def test_allocating(self) -> None:
        assert _map_deluge_state("Allocating") == "downloading"

    def test_unknown_lowercased(self) -> None:
        assert _map_deluge_state("SomeNewState") == "somenewstate"


# ── Client state labels ──────────────────────────────────────────


@pytest.mark.asyncio
class TestClientStateLabels:
    """States that set a human-readable client_state value."""

    async def test_checking_has_client_state(self) -> None:
        client = _make_client()
        client._authenticated = True
        mock_rpc = AsyncMock()
        mock_rpc.return_value = {
            "name": "T",
            "state": "Checking",
            "progress": 50.0,
            "total_size": 100,
            "download_payload_rate": 0,
            "eta": 0.0,
            "save_path": "/dl/",
            "message": "",
            "tracker_status": "",
        }
        client._rpc = mock_rpc  # type: ignore[assignment]
        status = await client.get_download_status("x")
        assert status.client_state == "Checking"

    async def test_moving_has_client_state(self) -> None:
        client = _make_client()
        client._authenticated = True
        mock_rpc = AsyncMock()
        mock_rpc.return_value = {
            "name": "T",
            "state": "Moving",
            "progress": 100.0,
            "total_size": 100,
            "download_payload_rate": 0,
            "eta": 0.0,
            "save_path": "/dl/",
            "message": "",
            "tracker_status": "",
        }
        client._rpc = mock_rpc  # type: ignore[assignment]
        status = await client.get_download_status("x")
        assert status.client_state == "Moving"

    async def test_allocating_has_client_state(self) -> None:
        client = _make_client()
        client._authenticated = True
        mock_rpc = AsyncMock()
        mock_rpc.return_value = {
            "name": "T",
            "state": "Allocating",
            "progress": 0.0,
            "total_size": 100,
            "download_payload_rate": 0,
            "eta": 0.0,
            "save_path": "/dl/",
            "message": "",
            "tracker_status": "",
        }
        client._rpc = mock_rpc  # type: ignore[assignment]
        status = await client.get_download_status("x")
        assert status.client_state == "Allocating"

    async def test_normal_downloading_no_client_state(self) -> None:
        client = _make_client()
        client._authenticated = True
        mock_rpc = AsyncMock()
        mock_rpc.return_value = {
            "name": "T",
            "state": "Downloading",
            "progress": 50.0,
            "total_size": 100,
            "download_payload_rate": 5000,
            "eta": 60.0,
            "save_path": "/dl/",
            "message": "",
            "tracker_status": "",
        }
        client._rpc = mock_rpc  # type: ignore[assignment]
        status = await client.get_download_status("x")
        assert status.client_state is None


# ── Properties ───────────────────────────────────────────────────


class TestProperties:
    """Tests for DelugeClient properties."""

    def test_name(self) -> None:
        assert _make_client().name == "deluge"

    def test_client_type(self) -> None:
        assert _make_client().client_type == "deluge"


# ── Label edge cases ────────────────────────────────────────────


@pytest.mark.asyncio
class TestLabelEdgeCases:
    """Edge cases for Deluge Label plugin handling."""

    async def test_label_with_spaces(self) -> None:
        """Labels with spaces should not be stripped."""
        client = _make_client(label="comic books")
        client._authenticated = True
        call_log: list[tuple[str, Any]] = []

        async def fake_rpc(method: str, params: list[Any] | None = None) -> Any:
            call_log.append((method, params))
            if method == "core.add_torrent_file":
                return "h1"
            if method == "label.get_labels":
                return ["comic books"]
            if method == "label.set_torrent":
                return None
            return None

        client._rpc = AsyncMock(side_effect=fake_rpc)  # type: ignore[assignment]
        with patch("httpx.AsyncClient", return_value=_mock_httpx_for_torrent()):
            await client.add_torrent("http://example.com/t.torrent", "Test")

        # Find the label.set_torrent call and check the label value
        set_calls = [c for c in call_log if c[0] == "label.set_torrent"]
        assert len(set_calls) == 1
        assert set_calls[0][1] == ["h1", "comic books"]
