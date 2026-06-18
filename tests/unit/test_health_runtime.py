"""Tests for shared health refresh runtime helpers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from pullbox.providers.base import ProviderHealthResult
from pullbox.services import health_runtime


class _SessionContext:
    def __init__(self, session: Any) -> None:
        self.session = session

    async def __aenter__(self) -> Any:
        return self.session

    async def __aexit__(self, *exc_info: object) -> None:
        return None


class _SessionFactory:
    def __init__(self, session: Any) -> None:
        self.session = session

    def __call__(self) -> _SessionContext:
        return _SessionContext(self.session)


class _FakeComicVineProvider:
    def __init__(self, *, api_key: str) -> None:
        self.api_key = api_key

    @property
    def name(self) -> str:
        return "ComicVine"

    async def test_connection(self) -> ProviderHealthResult:
        return ProviderHealthResult(True, "ok", 1.0)


def test_component_dependency_filters_are_component_specific() -> None:
    assert health_runtime._needs_indexers(None) is True
    assert health_runtime._needs_indexers("indexers") is True
    assert health_runtime._needs_indexers("database") is False

    assert health_runtime._needs_download_clients(None) is True
    assert health_runtime._needs_download_clients("download_clients") is True
    assert health_runtime._needs_download_clients("comicvine") is False

    assert health_runtime._needs_comicvine(None) is True
    assert health_runtime._needs_comicvine("comicvine") is True
    assert health_runtime._needs_comicvine("scheduler") is False


@pytest.mark.asyncio
async def test_build_health_service_skips_provider_registry_when_component_does_not_need_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace()
    scheduler = SimpleNamespace()
    session = SimpleNamespace()

    register_indexers = AsyncMock()
    register_download_clients = AsyncMock()
    monkeypatch.setattr(health_runtime, "get_settings", lambda: settings)
    monkeypatch.setattr(health_runtime, "get_scheduler", lambda: scheduler)
    monkeypatch.setattr(
        "pullbox.composition.providers.register_indexers",
        register_indexers,
    )
    monkeypatch.setattr(
        "pullbox.composition.providers.register_download_clients",
        register_download_clients,
    )

    service = await health_runtime.build_health_service(session, component="scheduler")

    assert service._settings is settings
    assert service._scheduler is scheduler
    assert service._registry is None
    assert service._bootstrap_errors == {}
    register_indexers.assert_not_awaited()
    register_download_clients.assert_not_awaited()


@pytest.mark.asyncio
async def test_build_health_service_bootstraps_requested_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace()
    scheduler = SimpleNamespace()
    session = SimpleNamespace()
    download_errors = [
        {"name": "SABnzbd", "status": "unhealthy", "message": "not reachable"},
    ]

    monkeypatch.setattr(health_runtime, "get_settings", lambda: settings)
    monkeypatch.setattr(health_runtime, "get_scheduler", lambda: scheduler)
    register_indexers = AsyncMock()
    register_download_clients = AsyncMock(return_value=download_errors)
    get_comicvine_api_key = AsyncMock(return_value="cv-key")
    monkeypatch.setattr(
        "pullbox.composition.providers.register_indexers",
        register_indexers,
    )
    monkeypatch.setattr(
        "pullbox.composition.providers.register_download_clients",
        register_download_clients,
    )
    monkeypatch.setattr(health_runtime, "get_comicvine_api_key", get_comicvine_api_key)
    monkeypatch.setattr(health_runtime, "ComicVineProvider", _FakeComicVineProvider)

    service = await health_runtime.build_health_service(session)

    register_indexers.assert_awaited_once_with(session, service._registry)
    register_download_clients.assert_awaited_once_with(session, service._registry)
    get_comicvine_api_key.assert_awaited_once_with(session)
    assert service._settings is settings
    assert service._scheduler is scheduler
    assert service._bootstrap_errors == {"download_clients": download_errors}
    assert service._registry is not None
    assert service._registry.get_metadata_provider("comicvine").api_key == "cv-key"


@pytest.mark.asyncio
async def test_build_health_service_records_bootstrap_errors_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = SimpleNamespace()

    monkeypatch.setattr(health_runtime, "get_settings", lambda: SimpleNamespace())
    monkeypatch.setattr(health_runtime, "get_scheduler", lambda: SimpleNamespace())
    monkeypatch.setattr(
        "pullbox.composition.providers.register_indexers",
        AsyncMock(side_effect=RuntimeError("indexer config exploded")),
    )
    monkeypatch.setattr(
        "pullbox.composition.providers.register_download_clients",
        AsyncMock(side_effect=ValueError("client config exploded")),
    )
    monkeypatch.setattr(
        health_runtime,
        "get_comicvine_api_key",
        AsyncMock(side_effect=RuntimeError("key lookup exploded")),
    )

    service = await health_runtime.build_health_service(session)

    assert service._registry is not None
    assert service._registry.has_metadata_provider("comicvine") is False
    assert service._bootstrap_errors == {
        "download_clients": [
            {
                "name": "Download clients",
                "status": "unhealthy",
                "message": "Configuration error: download clients could not be loaded.",
            }
        ]
    }


@pytest.mark.asyncio
async def test_build_health_service_ignores_comicvine_provider_registration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = SimpleNamespace()

    monkeypatch.setattr(health_runtime, "get_settings", lambda: SimpleNamespace())
    monkeypatch.setattr(health_runtime, "get_scheduler", lambda: SimpleNamespace())
    monkeypatch.setattr(
        "pullbox.composition.providers.register_indexers",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "pullbox.composition.providers.register_download_clients",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        health_runtime,
        "get_comicvine_api_key",
        AsyncMock(return_value="cv-key"),
    )
    monkeypatch.setattr(
        health_runtime,
        "ComicVineProvider",
        lambda *, api_key: (_ for _ in ()).throw(RuntimeError(f"bad key {api_key}")),
    )

    service = await health_runtime.build_health_service(session)

    assert service._registry is not None
    assert service._registry.has_metadata_provider("comicvine") is False
    assert service._bootstrap_errors == {}


@pytest.mark.asyncio
async def test_run_health_refresh_runs_all_checks_and_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = SimpleNamespace(commit=AsyncMock())
    service = SimpleNamespace(
        run_all_checks=AsyncMock(return_value=["all"]),
        run_check=AsyncMock(return_value=["component"]),
    )
    build_health_service = AsyncMock(return_value=service)
    monkeypatch.setattr(health_runtime, "get_session_factory", lambda: _SessionFactory(session))
    monkeypatch.setattr(health_runtime, "build_health_service", build_health_service)

    outcomes = await health_runtime.run_health_refresh()

    assert outcomes == ["all"]
    build_health_service.assert_awaited_once_with(session, component=None)
    service.run_all_checks.assert_awaited_once_with(session)
    service.run_check.assert_not_awaited()
    session.commit.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_run_health_refresh_runs_single_component_and_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = SimpleNamespace(commit=AsyncMock())
    service = SimpleNamespace(
        run_all_checks=AsyncMock(return_value=["all"]),
        run_check=AsyncMock(return_value=["database"]),
    )
    build_health_service = AsyncMock(return_value=service)
    monkeypatch.setattr(health_runtime, "get_session_factory", lambda: _SessionFactory(session))
    monkeypatch.setattr(health_runtime, "build_health_service", build_health_service)

    outcomes = await health_runtime.run_health_refresh(component="database")

    assert outcomes == ["database"]
    build_health_service.assert_awaited_once_with(session, component="database")
    service.run_check.assert_awaited_once_with(session, "database")
    service.run_all_checks.assert_not_awaited()
    session.commit.assert_awaited_once_with()
