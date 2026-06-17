"""Docker healthcheck scheme selection for native HTTPS."""

from __future__ import annotations

import runpy
import ssl
import sys
from types import SimpleNamespace
from typing import ClassVar

import pytest


class _FakeResponse:
    def __init__(self, status: int) -> None:
        self.status = status


class _FakeConnection:
    calls: ClassVar[list[tuple[str, int, object | None]]] = []
    requests: ClassVar[list[tuple[str, str, dict[str, str]]]] = []
    close_count: ClassVar[int] = 0
    response_status: ClassVar[int] = 200
    request_error: ClassVar[OSError | None] = None

    def __init__(self, host: str, port: int, timeout: int = 5, context: object | None = None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.context = context
        self.__class__.calls.append((host, port, context))

    def request(self, method: str, path: str, headers: dict[str, str]) -> None:
        if self.__class__.request_error is not None:
            raise self.__class__.request_error
        self.__class__.requests.append((method, path, headers))

    def getresponse(self) -> _FakeResponse:
        return _FakeResponse(self.__class__.response_status)

    def close(self) -> None:
        self.__class__.close_count += 1


def _reset_fake_connection() -> None:
    _FakeConnection.calls = []
    _FakeConnection.requests = []
    _FakeConnection.close_count = 0
    _FakeConnection.response_status = 200
    _FakeConnection.request_error = None


def test_healthcheck_port_defaults_invalid_values(monkeypatch) -> None:
    from pullbox import docker_healthcheck

    for value in ("not-a-port", "0", "65536", "-1"):
        monkeypatch.setenv("PULLBOX_PORT", value)
        assert docker_healthcheck._healthcheck_port() == 8585

    monkeypatch.setenv("PULLBOX_PORT", "1")
    assert docker_healthcheck._healthcheck_port() == 1

    monkeypatch.setenv("PULLBOX_PORT", "65535")
    assert docker_healthcheck._healthcheck_port() == 65535


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
    assert _FakeConnection.close_count == 1


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
    assert _FakeConnection.close_count == 1


def test_healthcheck_exits_when_ping_is_not_healthy(monkeypatch) -> None:
    from pullbox import docker_healthcheck

    _reset_fake_connection()
    _FakeConnection.response_status = 503
    monkeypatch.setattr(docker_healthcheck, "HTTPConnection", _FakeConnection)
    monkeypatch.setattr(
        docker_healthcheck,
        "resolve_https_runtime_settings",
        lambda: SimpleNamespace(enabled=False),
        raising=False,
    )

    with pytest.raises(SystemExit) as exc_info:
        docker_healthcheck.main()

    assert exc_info.value.code == 1
    assert _FakeConnection.close_count == 1


def test_healthcheck_exits_when_connection_raises_os_error(monkeypatch) -> None:
    from pullbox import docker_healthcheck

    _reset_fake_connection()
    _FakeConnection.request_error = OSError("connection refused")
    monkeypatch.setattr(docker_healthcheck, "HTTPConnection", _FakeConnection)
    monkeypatch.setattr(
        docker_healthcheck,
        "resolve_https_runtime_settings",
        lambda: SimpleNamespace(enabled=False),
        raising=False,
    )

    with pytest.raises(SystemExit) as exc_info:
        docker_healthcheck.main()

    assert exc_info.value.code == 1
    assert _FakeConnection.close_count == 1


def test_module_entrypoint_runs_healthcheck(monkeypatch) -> None:
    """``python -m pullbox.docker_healthcheck`` should run the same main path."""
    import http.client

    import pullbox.core.https_runtime as https_runtime

    _reset_fake_connection()
    monkeypatch.delitem(sys.modules, "pullbox.docker_healthcheck", raising=False)
    monkeypatch.setattr(http.client, "HTTPConnection", _FakeConnection)
    monkeypatch.setattr(
        https_runtime,
        "resolve_https_runtime_settings",
        lambda: SimpleNamespace(enabled=False),
    )

    runpy.run_module("pullbox.docker_healthcheck", run_name="__main__")

    assert _FakeConnection.requests == [
        ("GET", "/ping", {"Accept": "application/json"}),
    ]
