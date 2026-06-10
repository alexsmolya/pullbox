"""Unit tests for client options discovery API (DCE-S.5).

Tests get_options() on all 5 download client implementations.

Run:
    pytest tests/unit/test_client_options_discovery.py -v
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from pullbox.providers.download.deluge import DelugeClient, DelugeError
from pullbox.providers.download.nzbget import NZBGetClient
from pullbox.providers.download.qbittorrent import QBittorrentClient
from pullbox.providers.download.sabnzbd import SABnzbdClient
from pullbox.providers.download.transmission import TransmissionClient

# ── SABnzbd ──────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestSABnzbdOptions:
    """Tests for SABnzbdClient.get_options()."""

    async def test_returns_categories(self) -> None:
        client = SABnzbdClient(url="http://localhost:8080", api_key="test")
        mock_request = AsyncMock(return_value={"categories": ["Default", "comics", "tv"]})
        client._request = mock_request  # type: ignore[assignment]

        options = await client.get_options()
        assert options.categories == ["Default", "comics", "tv"]

    async def test_empty_categories_returns_default(self) -> None:
        client = SABnzbdClient(url="http://localhost:8080", api_key="test")
        mock_request = AsyncMock(return_value={"categories": []})
        client._request = mock_request  # type: ignore[assignment]

        options = await client.get_options()
        assert options.categories == ["Default"]

    async def test_no_categories_key_returns_default(self) -> None:
        client = SABnzbdClient(url="http://localhost:8080", api_key="test")
        mock_request = AsyncMock(return_value={})
        client._request = mock_request  # type: ignore[assignment]

        options = await client.get_options()
        assert options.categories == ["Default"]

    async def test_unicode_category(self) -> None:
        client = SABnzbdClient(url="http://localhost:8080", api_key="test")
        mock_request = AsyncMock(return_value={"categories": ["漫画"]})
        client._request = mock_request  # type: ignore[assignment]

        options = await client.get_options()
        assert options.categories == ["漫画"]


# ── NZBGet ───────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestNZBGetOptions:
    """Tests for NZBGetClient.get_options()."""

    async def test_parses_categories_from_config(self) -> None:
        client = NZBGetClient(url="http://localhost:6789", password="test")
        config_data = [
            {"Name": "Category1.Name", "Value": "comics"},
            {"Name": "Category1.DestDir", "Value": "/dl/comics"},
            {"Name": "Category2.Name", "Value": "tv"},
            {"Name": "Category2.DestDir", "Value": "/dl/tv"},
            {"Name": "MainDir", "Value": "/data"},
        ]
        mock_call = AsyncMock(return_value=config_data)
        client._call = mock_call  # type: ignore[assignment]

        options = await client.get_options()
        assert options.categories == ["comics", "tv"]

    async def test_no_categories_returns_empty(self) -> None:
        client = NZBGetClient(url="http://localhost:6789", password="test")
        mock_call = AsyncMock(return_value=[{"Name": "MainDir", "Value": "/data"}])
        client._call = mock_call  # type: ignore[assignment]

        options = await client.get_options()
        assert options.categories == []

    async def test_empty_category_name_skipped(self) -> None:
        client = NZBGetClient(url="http://localhost:6789", password="test")
        config_data = [
            {"Name": "Category1.Name", "Value": ""},
            {"Name": "Category2.Name", "Value": "comics"},
        ]
        mock_call = AsyncMock(return_value=config_data)
        client._call = mock_call  # type: ignore[assignment]

        options = await client.get_options()
        assert options.categories == ["comics"]


# ── qBittorrent ──────────────────────────────────────────────────


@pytest.mark.asyncio
class TestQBittorrentOptions:
    """Tests for QBittorrentClient.get_options()."""

    async def test_returns_sorted_categories(self) -> None:
        client = QBittorrentClient(
            url="http://localhost:8080",
            username="admin",
            password="test",
        )
        resp = MagicMock()
        resp.json.return_value = {
            "tv": {"savePath": "/dl/tv"},
            "comics": {"savePath": "/dl/comics"},
            "movies": {"savePath": ""},
        }
        resp.status_code = 200
        mock_request = AsyncMock(return_value=resp)
        client._request = mock_request  # type: ignore[assignment]

        options = await client.get_options()
        assert options.categories == ["comics", "movies", "tv"]

    async def test_returns_save_paths(self) -> None:
        client = QBittorrentClient(
            url="http://localhost:8080",
            username="admin",
            password="test",
        )
        resp = MagicMock()
        resp.json.return_value = {"comics": {"savePath": "/dl/comics"}}
        resp.status_code = 200
        mock_request = AsyncMock(return_value=resp)
        client._request = mock_request  # type: ignore[assignment]

        options = await client.get_options()
        assert options.download_directories == ["/dl/comics"]

    async def test_no_categories(self) -> None:
        client = QBittorrentClient(
            url="http://localhost:8080",
            username="admin",
            password="test",
        )
        resp = MagicMock()
        resp.json.return_value = {}
        resp.status_code = 200
        mock_request = AsyncMock(return_value=resp)
        client._request = mock_request  # type: ignore[assignment]

        options = await client.get_options()
        assert options.categories == []
        assert options.download_directories is None


# ── Transmission ─────────────────────────────────────────────────


@pytest.mark.asyncio
class TestTransmissionOptions:
    """Tests for TransmissionClient.get_options()."""

    async def test_returns_download_dir(self) -> None:
        client = TransmissionClient(url="http://localhost:9091")
        mock_rpc = AsyncMock(return_value={"download-dir": "/mnt/downloads"})
        client._rpc = mock_rpc  # type: ignore[assignment]

        options = await client.get_options()
        assert options.categories == []
        assert options.download_directories == ["/mnt/downloads"]

    async def test_no_download_dir(self) -> None:
        client = TransmissionClient(url="http://localhost:9091")
        mock_rpc = AsyncMock(return_value={})
        client._rpc = mock_rpc  # type: ignore[assignment]

        options = await client.get_options()
        assert options.categories == []
        assert options.download_directories is None


# ── Deluge ───────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestDelugeOptions:
    """Tests for DelugeClient.get_options()."""

    async def test_with_label_plugin(self) -> None:
        client = DelugeClient(url="http://localhost:8112", password="deluge")
        client._authenticated = True
        mock_rpc = AsyncMock(return_value=["comics", "tv", "movies"])
        client._rpc = mock_rpc  # type: ignore[assignment]

        options = await client.get_options()
        assert options.categories == ["comics", "tv", "movies"]
        assert options.extra["label_plugin"] is True

    async def test_without_label_plugin(self) -> None:
        client = DelugeClient(url="http://localhost:8112", password="deluge")
        client._authenticated = True
        mock_rpc = AsyncMock(side_effect=DelugeError("Unknown method"))
        client._rpc = mock_rpc  # type: ignore[assignment]

        options = await client.get_options()
        assert options.categories == []
        assert options.extra["label_plugin"] is False

    async def test_empty_labels(self) -> None:
        client = DelugeClient(url="http://localhost:8112", password="deluge")
        client._authenticated = True
        mock_rpc = AsyncMock(return_value=[])
        client._rpc = mock_rpc  # type: ignore[assignment]

        options = await client.get_options()
        assert options.categories == []
        assert options.extra["label_plugin"] is True


# ── hasattr check ────────────────────────────────────────────────


class TestHasGetOptions:
    """All 5 client implementations have get_options()."""

    def test_sabnzbd_has_get_options(self) -> None:
        client = SABnzbdClient(url="http://x", api_key="k")
        assert hasattr(client, "get_options")

    def test_nzbget_has_get_options(self) -> None:
        client = NZBGetClient(url="http://x", password="p")
        assert hasattr(client, "get_options")

    def test_qbittorrent_has_get_options(self) -> None:
        client = QBittorrentClient(url="http://x", username="u", password="p")
        assert hasattr(client, "get_options")

    def test_transmission_has_get_options(self) -> None:
        client = TransmissionClient(url="http://x")
        assert hasattr(client, "get_options")

    def test_deluge_has_get_options(self) -> None:
        client = DelugeClient(url="http://x", password="p")
        assert hasattr(client, "get_options")
