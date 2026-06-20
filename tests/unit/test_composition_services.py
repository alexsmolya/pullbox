"""Characterization tests for neutral service composition helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from pullbox.composition import services
from pullbox.core import events as core_events
from pullbox.core.events import get_event_bus
from pullbox.models import Base
from pullbox.models.config import SystemConfig
from pullbox.services.comicvine_persistent_cache import PersistentComicVineCacheProvider
from pullbox.services.download_service import DownloadService
from pullbox.services.import_service import ImportService
from pullbox.services.matching_service import MatchingService
from pullbox.services.metadata_service import MetadataService
from pullbox.services.series_service import SeriesService


@pytest.mark.asyncio
async def test_build_metadata_service_uses_persisted_comicvine_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock()
    provider = MagicMock()
    covers_dir = Path("/tmp/pullbox-covers")

    get_key = AsyncMock(return_value="cv-key")
    resolve_covers = AsyncMock(return_value=covers_dir)
    provider_cls = MagicMock(return_value=provider)

    monkeypatch.setattr(
        services,
        "get_settings",
        lambda: SimpleNamespace(metadata_refresh_days=17),
    )
    monkeypatch.setattr(services, "get_comicvine_api_key", get_key)
    monkeypatch.setattr(services, "resolve_covers_dir", resolve_covers)
    monkeypatch.setattr(services, "ComicVineProvider", provider_cls)

    metadata_service = await services.build_metadata_service(session)

    assert isinstance(metadata_service, MetadataService)
    provider_cls.assert_called_once_with(api_key="cv-key")
    get_key.assert_awaited_once_with(session)
    resolve_covers.assert_awaited_once_with(session)
    assert metadata_service._provider is provider
    assert metadata_service._covers_dir == covers_dir
    assert metadata_service._refresh_days == 17


def test_production_code_uses_neutral_metadata_composition() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    src_root = repo_root / "src" / "pullbox"
    offenders: list[str] = []

    for path in src_root.rglob("*.py"):
        rel_path = path.relative_to(src_root).as_posix()
        if rel_path == "api/v1/series.py":
            continue
        text = path.read_text()
        if "pullbox.api.v1.series import _build_metadata_service" in text:
            offenders.append(path.relative_to(repo_root).as_posix())

    assert offenders == []


def test_build_series_service_uses_domain_event_bus(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core_events, "_event_bus_instance", None)
    metadata_service = MagicMock()

    series_service = services.build_series_service(metadata_service)

    assert isinstance(series_service, SeriesService)
    assert series_service._metadata is metadata_service
    assert series_service._event_bus is get_event_bus()


@pytest.mark.asyncio
async def test_build_domain_series_service_delegates_metadata_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(core_events, "_event_bus_instance", None)
    session = MagicMock()
    metadata_service = MagicMock()
    build_metadata_service = AsyncMock(return_value=metadata_service)

    monkeypatch.setattr(services, "build_metadata_service", build_metadata_service)

    series_service = await services.build_domain_series_service(session)

    assert isinstance(series_service, SeriesService)
    assert series_service._metadata is metadata_service
    assert series_service._event_bus is get_event_bus()
    build_metadata_service.assert_awaited_once_with(session)


def test_build_matching_service_uses_domain_event_bus(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core_events, "_event_bus_instance", None)

    matching_service = services.build_matching_service()

    assert isinstance(matching_service, MatchingService)
    assert matching_service._event_bus is get_event_bus()


@pytest.mark.asyncio
async def test_build_import_service_falls_back_to_bootstrap_rate_limit_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock()
    session.get = AsyncMock(return_value=None)
    provider = MagicMock()
    covers_dir = Path("/tmp/pullbox-import-covers")

    get_key = AsyncMock(return_value=None)
    resolve_covers = AsyncMock(return_value=covers_dir)
    provider_cls = MagicMock(return_value=provider)

    monkeypatch.setattr(
        services,
        "get_settings",
        lambda: SimpleNamespace(comicvine_rate_limit=2.5, metadata_refresh_days=9),
    )
    monkeypatch.setattr(services, "get_comicvine_api_key", get_key)
    monkeypatch.setattr(services, "resolve_covers_dir", resolve_covers)
    monkeypatch.setattr(services, "ComicVineProvider", provider_cls)

    import_service = await services.build_import_service(session)

    assert isinstance(import_service, ImportService)
    provider_cls.assert_called_once_with(api_key="", rate_limit=2, burst_limit=1)
    get_key.assert_awaited_once_with(session)
    resolve_covers.assert_awaited_once_with(session)
    assert import_service._metadata_service._provider is provider
    assert import_service._metadata_service._covers_dir == covers_dir
    assert import_service._metadata_service._refresh_days == 9


@pytest.mark.asyncio
async def test_build_import_service_uses_persistent_cache_for_file_sqlite(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'pullbox.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    provider = MagicMock()
    covers_dir = Path("/tmp/pullbox-import-covers")
    get_key = AsyncMock(return_value=None)
    resolve_covers = AsyncMock(return_value=covers_dir)
    provider_cls = MagicMock(return_value=provider)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    monkeypatch.setattr(
        services,
        "get_settings",
        lambda: SimpleNamespace(comicvine_rate_limit=2.5, metadata_refresh_days=9),
    )
    monkeypatch.setattr(services, "get_comicvine_api_key", get_key)
    monkeypatch.setattr(services, "resolve_covers_dir", resolve_covers)
    monkeypatch.setattr(services, "ComicVineProvider", provider_cls)

    try:
        async with session_factory() as session:
            import_service = await services.build_import_service(session)
    finally:
        await engine.dispose()

    wrapped_provider = import_service._metadata_service._provider
    assert isinstance(wrapped_provider, PersistentComicVineCacheProvider)
    assert wrapped_provider._provider is provider


@pytest.mark.asyncio
async def test_build_import_service_uses_persisted_ui_burst_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock()
    session.get = AsyncMock(
        return_value=SystemConfig(
            key="comicvine_rate_limit_per_second",
            value="3",
            value_type="int",
        )
    )
    provider = MagicMock()
    covers_dir = Path("/tmp/pullbox-import-covers")

    get_key = AsyncMock(return_value=None)
    resolve_covers = AsyncMock(return_value=covers_dir)
    provider_cls = MagicMock(return_value=provider)

    monkeypatch.setattr(
        services,
        "get_settings",
        lambda: SimpleNamespace(comicvine_rate_limit=2.5, metadata_refresh_days=9),
    )
    monkeypatch.setattr(services, "get_comicvine_api_key", get_key)
    monkeypatch.setattr(services, "resolve_covers_dir", resolve_covers)
    monkeypatch.setattr(services, "ComicVineProvider", provider_cls)

    import_service = await services.build_import_service(session)

    assert isinstance(import_service, ImportService)
    provider_cls.assert_called_once_with(api_key="", rate_limit=2, burst_limit=3)


@pytest.mark.asyncio
async def test_build_import_service_respects_interactive_min_burst_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock()
    session.get = AsyncMock(
        return_value=SystemConfig(
            key="comicvine_rate_limit_per_second",
            value="1",
            value_type="int",
        )
    )
    provider = MagicMock()
    covers_dir = Path("/tmp/pullbox-import-covers")

    get_key = AsyncMock(return_value=None)
    resolve_covers = AsyncMock(return_value=covers_dir)
    provider_cls = MagicMock(return_value=provider)

    monkeypatch.setattr(
        services,
        "get_settings",
        lambda: SimpleNamespace(comicvine_rate_limit=2.5, metadata_refresh_days=9),
    )
    monkeypatch.setattr(services, "get_comicvine_api_key", get_key)
    monkeypatch.setattr(services, "resolve_covers_dir", resolve_covers)
    monkeypatch.setattr(services, "ComicVineProvider", provider_cls)

    import_service = await services.build_import_service(session, min_burst_limit=3)

    assert isinstance(import_service, ImportService)
    provider_cls.assert_called_once_with(api_key="", rate_limit=2, burst_limit=3)


def test_build_import_control_service_uses_empty_dependency_slots() -> None:
    import_service = services.build_import_control_service()

    assert isinstance(import_service, ImportService)
    assert import_service._series_service is None
    assert import_service._metadata_service is None
    assert import_service._event_bus is None


def test_import_service_shims_are_the_only_legacy_composition_paths() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    src_root = repo_root / "src" / "pullbox"
    allowed = {"api/v1/import_jobs.py", "tasks/import_task.py"}
    offenders: list[str] = []

    for path in src_root.rglob("*.py"):
        rel_path = path.relative_to(src_root).as_posix()
        text = path.read_text()
        if "_build_import_service" in text and rel_path not in allowed:
            offenders.append(path.relative_to(repo_root).as_posix())

    assert offenders == []


def test_production_lightweight_import_service_construction_stays_in_composition() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    src_root = repo_root / "src" / "pullbox"
    allowed = {"composition/services.py"}
    offenders: list[str] = []

    for path in src_root.rglob("*.py"):
        rel_path = path.relative_to(src_root).as_posix()
        if rel_path in allowed:
            continue

        text = path.read_text()
        if "series_service=None" in text and "metadata_service=None" in text:
            offenders.append(path.relative_to(repo_root).as_posix())

    assert offenders == []


def test_build_download_service_uses_domain_event_bus(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core_events, "_event_bus_instance", None)
    registry = MagicMock()

    download_service = services.build_download_service(registry)

    assert isinstance(download_service, DownloadService)
    assert download_service._registry is registry
    assert download_service._event_bus is get_event_bus()


@pytest.mark.asyncio
async def test_build_domain_download_service_delegates_registry_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(core_events, "_event_bus_instance", None)
    session = MagicMock()
    registry = MagicMock()
    indexer_configs = {42: MagicMock()}
    build_registry = AsyncMock(return_value=(registry, indexer_configs))

    monkeypatch.setattr(services.providers, "build_registry", build_registry)

    result = await services.build_domain_download_service(session)

    assert result is not None
    download_service, configs = result
    assert isinstance(download_service, DownloadService)
    assert download_service._registry is registry
    assert download_service._event_bus is get_event_bus()
    assert configs is indexer_configs
    build_registry.assert_awaited_once_with(session)


@pytest.mark.asyncio
async def test_build_domain_download_service_returns_none_without_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock()
    build_registry = AsyncMock(return_value=None)

    monkeypatch.setattr(services.providers, "build_registry", build_registry)

    assert await services.build_domain_download_service(session) is None
    build_registry.assert_awaited_once_with(session)
