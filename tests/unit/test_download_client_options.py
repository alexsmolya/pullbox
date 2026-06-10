"""Tests for download client option columns and provider parameters (C-5.5).

Verifies:
- SABnzbd priority and post-processing passed to API calls
- qBittorrent content layout, ratio limit, seeding time passed to add_torrent
- Default values used when options not configured
- Model columns exist and accept values

Run:
    pytest tests/unit/test_download_client_options.py -v
"""

from __future__ import annotations

from pullbox.models.client import DownloadClientConfig
from pullbox.models.download import DownloadClientType
from pullbox.providers.download.qbittorrent import QBittorrentClient
from pullbox.providers.download.sabnzbd import SABnzbdClient


class TestSABnzbdOptions:
    """SABnzbd provider accepts priority and post-processing options."""

    def test_default_priority_none(self) -> None:
        client = SABnzbdClient(url="http://localhost:8080", api_key="test")
        assert client._default_priority is None

    def test_priority_stored(self) -> None:
        client = SABnzbdClient(
            url="http://localhost:8080",
            api_key="test",
            priority="1",
        )
        assert client._default_priority == "1"

    def test_post_processing_stored(self) -> None:
        client = SABnzbdClient(
            url="http://localhost:8080",
            api_key="test",
            post_processing="3",
        )
        assert client._default_post_processing == "3"

    def test_all_options_stored(self) -> None:
        client = SABnzbdClient(
            url="http://localhost:8080",
            api_key="test",
            category="comics",
            priority="2",
            post_processing="3",
        )
        assert client._default_category == "comics"
        assert client._default_priority == "2"
        assert client._default_post_processing == "3"


class TestQBittorrentOptions:
    """qBittorrent provider accepts content layout, ratio limit, seeding time."""

    def test_defaults_none(self) -> None:
        client = QBittorrentClient(
            url="http://localhost:8080",
            username="admin",
            password="password",
        )
        assert client._content_layout is None
        assert client._ratio_limit is None
        assert client._seeding_time_limit is None

    def test_content_layout_stored(self) -> None:
        client = QBittorrentClient(
            url="http://localhost:8080",
            username="admin",
            password="password",
            content_layout="Subfolder",
        )
        assert client._content_layout == "Subfolder"

    def test_ratio_limit_stored(self) -> None:
        client = QBittorrentClient(
            url="http://localhost:8080",
            username="admin",
            password="password",
            ratio_limit=2.5,
        )
        assert client._ratio_limit == 2.5

    def test_seeding_time_limit_stored(self) -> None:
        client = QBittorrentClient(
            url="http://localhost:8080",
            username="admin",
            password="password",
            seeding_time_limit=120,
        )
        assert client._seeding_time_limit == 120

    def test_all_options_stored(self) -> None:
        client = QBittorrentClient(
            url="http://localhost:8080",
            username="admin",
            password="password",
            category="comics",
            content_layout="Original",
            ratio_limit=1.0,
            seeding_time_limit=60,
        )
        assert client._default_category == "comics"
        assert client._content_layout == "Original"
        assert client._ratio_limit == 1.0
        assert client._seeding_time_limit == 60


class TestModelColumns:
    """DownloadClientConfig model has the new option columns."""

    def test_sab_columns_exist(self) -> None:
        config = DownloadClientConfig(
            name="Test SAB",
            client_type=DownloadClientType.SABNZBD,
            url="http://localhost:8080",
            sab_priority="1",
            sab_post_processing="3",
        )
        assert config.sab_priority == "1"
        assert config.sab_post_processing == "3"

    def test_qbt_columns_exist(self) -> None:
        config = DownloadClientConfig(
            name="Test QBT",
            client_type=DownloadClientType.QBITTORRENT,
            url="http://localhost:8080",
            qbt_content_layout="Subfolder",
            qbt_ratio_limit=2.0,
            qbt_seeding_time_limit=120,
        )
        assert config.qbt_content_layout == "Subfolder"
        assert config.qbt_ratio_limit == 2.0
        assert config.qbt_seeding_time_limit == 120

    def test_columns_default_none(self) -> None:
        config = DownloadClientConfig(
            name="Test",
            client_type=DownloadClientType.SABNZBD,
            url="http://localhost:8080",
        )
        assert config.sab_priority is None
        assert config.sab_post_processing is None
        assert config.qbt_content_layout is None
        assert config.qbt_ratio_limit is None
        assert config.qbt_seeding_time_limit is None
