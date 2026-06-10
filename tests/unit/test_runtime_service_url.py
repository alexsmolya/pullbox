"""Tests for runtime-aware service URL normalization."""

from __future__ import annotations

from pullbox.core import config_resolver
from pullbox.providers.download.deluge import DelugeClient
from pullbox.providers.download.nzbget import NZBGetClient
from pullbox.providers.download.transmission import TransmissionClient


class TestResolveRuntimeServiceUrl:
    """Loopback service URLs should stay usable from containerized Pullbox."""

    def test_host_runtime_keeps_loopback_url(self, monkeypatch) -> None:
        monkeypatch.setattr(config_resolver, "is_container_runtime", lambda: False)

        assert (
            config_resolver.resolve_runtime_service_url("http://localhost:8112")
            == "http://localhost:8112"
        )

    def test_container_runtime_rewrites_localhost(self, monkeypatch) -> None:
        monkeypatch.setattr(config_resolver, "is_container_runtime", lambda: True)

        assert (
            config_resolver.resolve_runtime_service_url("http://localhost:8112")
            == "http://host.docker.internal:8112"
        )

    def test_container_runtime_rewrites_loopback_ipv4(self, monkeypatch) -> None:
        monkeypatch.setattr(config_resolver, "is_container_runtime", lambda: True)

        assert (
            config_resolver.resolve_runtime_service_url("http://127.0.0.1:9091/transmission/rpc")
            == "http://host.docker.internal:9091/transmission/rpc"
        )

    def test_container_runtime_preserves_userinfo_and_path(self, monkeypatch) -> None:
        monkeypatch.setattr(config_resolver, "is_container_runtime", lambda: True)

        assert (
            config_resolver.resolve_runtime_service_url(
                "http://user:pass@localhost:6789/custom/path"
            )
            == "http://user:pass@host.docker.internal:6789/custom/path"
        )

    def test_non_loopback_url_is_unchanged(self, monkeypatch) -> None:
        monkeypatch.setattr(config_resolver, "is_container_runtime", lambda: True)

        assert (
            config_resolver.resolve_runtime_service_url("http://192.168.1.50:8112")
            == "http://192.168.1.50:8112"
        )


class TestDownloadClientUrlNormalization:
    """Download providers should apply the shared runtime URL rules."""

    def test_transmission_client_rewrites_rpc_base_url(self, monkeypatch) -> None:
        monkeypatch.setattr(config_resolver, "is_container_runtime", lambda: True)

        client = TransmissionClient(url="http://localhost:9091")

        assert client._base_url == "http://host.docker.internal:9091"
        assert client._rpc_url == "http://host.docker.internal:9091/transmission/rpc"

    def test_deluge_client_rewrites_base_url(self, monkeypatch) -> None:
        monkeypatch.setattr(config_resolver, "is_container_runtime", lambda: True)

        client = DelugeClient(url="http://127.0.0.1:8112", password="deluge")

        assert client._base_url == "http://host.docker.internal:8112"

    def test_nzbget_client_rewrites_xmlrpc_url(self, monkeypatch) -> None:
        monkeypatch.setattr(config_resolver, "is_container_runtime", lambda: True)

        client = NZBGetClient(url="http://localhost:6789", password="test")

        assert client._base_url == "http://host.docker.internal:6789"
        assert client._rpc_url == "http://nzbget:test@host.docker.internal:6789/xmlrpc"
