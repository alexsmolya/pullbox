"""Docker healthcheck scheme selection for native HTTPS."""

from __future__ import annotations

import ssl
from types import SimpleNamespace
from typing import ClassVar


class _FakeResponse:
    status = 200


class _FakeConnection:
    calls: ClassVar[list[tuple[str, int, object | None]]] = []
    requests: ClassVar[list[tuple[str, str, dict[str, str]]]] = []

    def __init__(self, host: str, port: int, timeout: int = 5, context: object | None = None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.context = context
        self.__class__.calls.append((host, port, context))

    def request(self, method: str, path: str, headers: dict[str, str]) -> None:
        self.__class__.requests.append((method, path, headers))

    def getresponse(self) -> _FakeResponse:
        return _FakeResponse()

    def close(self) -> None:
        return None


def _reset_fake_connection() -> None:
    _FakeConnection.calls = []
    _FakeConnection.requests = []


def test_healthcheck_uses_http_when_https_disabled(monkeypatch) -> None:
    from pullbox import docker_healthcheck

    _reset_fake_connection()
    monkeypatch.setenv("PULLBOX_PORT", "8585")
    monkeypatch.setattr(docker_healthcheck, "HTTPConnection", _FakeConnection)
    monkeypatch.setattr(docker_healthcheck, "HTTPSConnection", object, raising=False)
    monkeypatch.setattr(
        docker_healthcheck,
        "resolve_https_runtime_settings",
        lambda: SimpleNamespace(enabled=False),
        raising=False,
    )

    docker_healthcheck.main()

    assert _FakeConnection.calls == [("127.0.0.1", 8585, None)]
    assert _FakeConnection.requests == [
        ("GET", "/ping", {"Accept": "application/json"}),
    ]


def test_healthcheck_uses_https_without_cert_verification_when_enabled(monkeypatch) -> None:
    from pullbox import docker_healthcheck

    _reset_fake_connection()
    context_marker = object()
    monkeypatch.setenv("PULLBOX_PORT", "9443")
    monkeypatch.setattr(docker_healthcheck, "HTTPSConnection", _FakeConnection, raising=False)
    monkeypatch.setattr(docker_healthcheck, "HTTPConnection", object)
    monkeypatch.setattr(
        docker_healthcheck,
        "resolve_https_runtime_settings",
        lambda: SimpleNamespace(enabled=True),
        raising=False,
    )
    monkeypatch.setattr(docker_healthcheck, "ssl", ssl, raising=False)
    monkeypatch.setattr(
        docker_healthcheck.ssl,
        "_create_unverified_context",
        lambda: context_marker,
        raising=False,
    )

    docker_healthcheck.main()

    assert _FakeConnection.calls == [("127.0.0.1", 9443, context_marker)]
    assert _FakeConnection.requests == [
        ("GET", "/ping", {"Accept": "application/json"}),
    ]
