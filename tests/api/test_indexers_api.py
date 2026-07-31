"""API route contracts for indexer configuration and Prowlarr sync."""

from __future__ import annotations

import os
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, ClassVar

import pytest
from sqlalchemy.exc import OperationalError

from pullbox.api.v1 import indexers as indexers_api
from pullbox.core.encryption import decrypt_secret, encrypt_secret, is_encrypted
from pullbox.core.exceptions import NotFoundError, ValidationError
from pullbox.models.config import SystemConfig
from pullbox.models.indexer import IndexerConfig, IndexerType
from pullbox.providers.base import ProviderHealthResult
from pullbox.schemas.indexer import (
    IndexerCreate,
    IndexerUpdate,
    JackettSyncRequest,
    ProwlarrSyncRequest,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

pytest_plugins = ["conftest_security"]


def _indexer_create(**overrides: object) -> IndexerCreate:
    payload: dict[str, object] = {
        "name": "NZBgeek",
        "indexer_type": "newznab",
        "url": "http://indexer.example",
        "api_key": "indexer-secret",
        "enabled": True,
        "priority": 25,
        "categories": "7030,7040",
    }
    payload.update(overrides)
    return IndexerCreate.model_validate(payload)


def _health(message: str = "reachable", *, healthy: bool = True) -> ProviderHealthResult:
    return ProviderHealthResult(
        healthy=healthy,
        message=message,
        response_time_ms=14.25,
    )


async def _instant_sleep(_seconds: float) -> None:
    return None


async def _seed_indexer(
    session: AsyncSession,
    *,
    name: str = "NZBgeek",
    indexer_type: IndexerType = IndexerType.NEWZNAB,
    api_key: str = "stored-secret",
    source: str = "manual",
    prowlarr_indexer_id: int | None = None,
    manager_indexer_id: str | None = None,
    manager_available: bool = True,
    enabled: bool = True,
    priority: int = 25,
    enable_rss: bool = True,
    enable_automatic_search: bool = True,
    enable_interactive_search: bool = True,
    resolver_enabled: bool = False,
) -> IndexerConfig:
    indexer = IndexerConfig(
        name=name,
        indexer_type=indexer_type,
        url="http://indexer.example",
        api_key=encrypt_secret(api_key),
        enabled=enabled,
        priority=priority,
        categories="7030",
        source=source,
        prowlarr_indexer_id=prowlarr_indexer_id,
        manager_indexer_id=manager_indexer_id,
        manager_available=manager_available,
        enable_rss=enable_rss,
        enable_automatic_search=enable_automatic_search,
        enable_interactive_search=enable_interactive_search,
        resolver_enabled=resolver_enabled,
    )
    session.add(indexer)
    await session.flush()
    return indexer


class _FakeProwlarrIndexer:
    remote_indexers: ClassVar[list[dict[str, Any]]] = []
    health = _health("Prowlarr is reachable")
    fail_on_get = False
    instances: ClassVar[list[_FakeProwlarrIndexer]] = []

    def __init__(self, *, url: str, api_key: str) -> None:
        self.url = url
        self.api_key = api_key
        self.closed = False
        self.instances.append(self)

    async def test_connection(self) -> ProviderHealthResult:
        return self.health

    async def get_indexers(self) -> list[dict[str, Any]]:
        if self.fail_on_get:
            raise RuntimeError("Prowlarr unavailable")
        return self.remote_indexers

    async def close(self) -> None:
        self.closed = True


class _FakeJackettClient:
    remote_indexers: ClassVar[list[SimpleNamespace]] = []
    health = _health("Jackett is reachable")
    fail_on_get = False
    instances: ClassVar[list[_FakeJackettClient]] = []

    def __init__(self, *, url: str, api_key: str) -> None:
        self.url = url
        self.api_key = api_key
        self.closed = False
        self.instances.append(self)

    async def test_connection(self) -> ProviderHealthResult:
        return self.health

    async def get_configured_indexers(self) -> list[SimpleNamespace]:
        if self.fail_on_get:
            raise RuntimeError("Jackett unavailable")
        return self.remote_indexers

    async def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _reset_fake_prowlarr() -> None:
    _FakeProwlarrIndexer.remote_indexers = []
    _FakeProwlarrIndexer.health = _health("Prowlarr is reachable")
    _FakeProwlarrIndexer.fail_on_get = False
    _FakeProwlarrIndexer.instances = []
    _FakeJackettClient.remote_indexers = []
    _FakeJackettClient.health = _health("Jackett is reachable")
    _FakeJackettClient.fail_on_get = False
    _FakeJackettClient.instances = []


@pytest.mark.asyncio
class TestIndexerCrudRoutes:
    async def test_crud_routes_redact_encrypt_preserve_and_delete(
        self,
        sec_db: async_sessionmaker[AsyncSession],
    ) -> None:
        async with sec_db() as session:
            first = await _seed_indexer(
                session,
                name="Zulu Torznab",
                indexer_type=IndexerType.TORZNAB,
                priority=40,
            )
            await _seed_indexer(session, name="Alpha Newznab", priority=10)

            listed = await indexers_api.list_indexers(object(), session)  # type: ignore[arg-type]
            assert [item.name for item in listed] == ["Alpha Newznab", "Zulu Torznab"]
            assert all(item.has_api_key for item in listed)

            created = await indexers_api.add_indexer(
                _indexer_create(name="Manual Torznab", indexer_type="torznab"),
                object(),  # type: ignore[arg-type]
                session,
            )
            assert created.name == "Manual Torznab"
            assert created.has_api_key is True
            stored = await session.get(IndexerConfig, created.id)
            assert stored is not None
            assert is_encrypted(stored.api_key)
            assert decrypt_secret(stored.api_key) == "indexer-secret"

            fetched = await indexers_api.get_indexer(first.id, object(), session)  # type: ignore[arg-type]
            assert fetched.name == "Zulu Torznab"

            blank_update = IndexerUpdate.model_construct(api_key="", priority=5)
            blank_result = await indexers_api.update_indexer(
                created.id,
                blank_update,
                object(),  # type: ignore[arg-type]
                session,
            )
            await session.refresh(stored)
            assert blank_result.priority == 5
            assert decrypt_secret(stored.api_key) == "indexer-secret"

            secret_result = await indexers_api.update_indexer(
                created.id,
                IndexerUpdate(api_key="rotated-key", categories="7030,8010"),
                object(),  # type: ignore[arg-type]
                session,
            )
            await session.refresh(stored)
            assert secret_result.categories == "7030,8010"
            assert decrypt_secret(stored.api_key) == "rotated-key"

            await indexers_api.delete_indexer(created.id, object(), session)  # type: ignore[arg-type]
            await session.flush()
            assert await session.get(IndexerConfig, created.id) is None

            with pytest.raises(NotFoundError):
                await indexers_api.get_indexer(999_001, object(), session)  # type: ignore[arg-type]
            with pytest.raises(NotFoundError):
                await indexers_api.update_indexer(
                    999_002,
                    IndexerUpdate(name="Missing"),
                    object(),  # type: ignore[arg-type]
                    session,
                )
            with pytest.raises(NotFoundError):
                await indexers_api.delete_indexer(999_003, object(), session)  # type: ignore[arg-type]

    async def test_manager_indexer_update_accepts_synced_category_lists(
        self,
        sec_db: async_sessionmaker[AsyncSession],
    ) -> None:
        categories = ",".join(str(category) for category in range(10_000, 10_100))

        async with sec_db() as session:
            indexer = await _seed_indexer(
                session,
                name="Large Category Set",
                source="prowlarr",
                prowlarr_indexer_id=42,
            )
            indexer.categories = categories
            await session.flush()

            updated = await indexers_api.update_indexer(
                indexer.id,
                IndexerUpdate(priority=7, categories=categories),
                object(),  # type: ignore[arg-type]
                session,
            )

        assert len(categories) > 255
        assert updated.priority == 7
        assert updated.categories == categories

    async def test_browser_resolver_is_opt_in_for_manual_torznab_only(
        self,
        sec_db: async_sessionmaker[AsyncSession],
    ) -> None:
        async with sec_db() as session:
            created = await indexers_api.add_indexer(
                _indexer_create(
                    name="Manual Torznab",
                    indexer_type="torznab",
                    resolver_enabled=True,
                ),
                object(),  # type: ignore[arg-type]
                session,
            )
            stored = await session.get(IndexerConfig, created.id)

            assert created.resolver_enabled is True
            assert stored is not None
            assert stored.resolver_enabled is True

            with pytest.raises(ValidationError, match="manual Torznab"):
                await indexers_api.add_indexer(
                    _indexer_create(resolver_enabled=True),
                    object(),  # type: ignore[arg-type]
                    session,
                )

            newznab = await _seed_indexer(session)
            with pytest.raises(ValidationError, match="manual Torznab"):
                await indexers_api.update_indexer(
                    newznab.id,
                    IndexerUpdate(resolver_enabled=True),
                    object(),  # type: ignore[arg-type]
                    session,
                )


@pytest.mark.asyncio
class TestProwlarrRoutes:
    async def test_prowlarr_connection_routes_use_inline_and_stored_credentials(
        self,
        sec_db: async_sessionmaker[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "pullbox.providers.indexer.prowlarr.ProwlarrIndexer",
            _FakeProwlarrIndexer,
        )

        async with sec_db() as session:
            inline = await indexers_api.test_prowlarr_connection(
                ProwlarrSyncRequest(
                    prowlarr_url="http://prowlarr:9696",
                    prowlarr_api_key="inline-key",
                ),
                object(),  # type: ignore[arg-type]
            )
            session.add_all(
                [
                    SystemConfig(key="prowlarr_url", value="http://stored-prowlarr:9696"),
                    SystemConfig(
                        key="prowlarr_api_key",
                        value=encrypt_secret("stored-key"),
                        value_type="secret",
                    ),
                ]
            )
            await session.flush()
            stored = await indexers_api.test_prowlarr_stored(object(), session)  # type: ignore[arg-type]

        assert inline["healthy"] is True
        assert stored["message"] == "Prowlarr is reachable"
        assert _FakeProwlarrIndexer.instances[0].api_key == "inline-key"
        assert _FakeProwlarrIndexer.instances[1].api_key == "stored-key"
        assert all(instance.closed for instance in _FakeProwlarrIndexer.instances)

    async def test_stored_prowlarr_routes_require_credentials(
        self,
        sec_db: async_sessionmaker[AsyncSession],
    ) -> None:
        async with sec_db() as session:
            with pytest.raises(NotFoundError):
                await indexers_api.test_prowlarr_stored(object(), session)  # type: ignore[arg-type]
            with pytest.raises(NotFoundError):
                await indexers_api.resync_prowlarr_indexers(object(), session)  # type: ignore[arg-type]

    async def test_sync_prowlarr_adds_updates_removes_and_saves_credentials(
        self,
        sec_db: async_sessionmaker[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "pullbox.providers.indexer.prowlarr.ProwlarrIndexer",
            _FakeProwlarrIndexer,
        )
        _FakeProwlarrIndexer.remote_indexers = [
            {
                "id": 7,
                "name": "MAM",
                "protocol": "torrent",
                "priority": 10,
                "enable": True,
                "capabilities": {"categories": [{"id": 7030}, {"id": 7040}]},
            },
            {
                "id": 8,
                "name": "NZBgeek",
                "protocol": "usenet",
                "priority": 20,
                "enable": False,
                "capabilities": {"categories": [{"id": 8010}]},
            },
            {"name": "Missing ID"},
        ]

        async with sec_db() as session:
            await _seed_indexer(
                session,
                name="Old MAM",
                source="prowlarr",
                prowlarr_indexer_id=7,
                priority=99,
            )
            stale = await _seed_indexer(
                session,
                name="Removed Source",
                source="prowlarr",
                prowlarr_indexer_id=99,
            )

            result = await indexers_api.sync_prowlarr_indexers(
                ProwlarrSyncRequest(
                    prowlarr_url="http://prowlarr:9696",
                    prowlarr_api_key="synced-key",
                ),
                object(),  # type: ignore[arg-type]
                session,
            )
            retained_stale = await session.get(IndexerConfig, stale.id)
            stored_url = await session.get(SystemConfig, "prowlarr_url")
            stored_key = await session.get(SystemConfig, "prowlarr_api_key")

        assert result.added == 1
        assert result.updated == 1
        assert result.removed == 1
        assert result.total == 2
        assert retained_stale is not None
        assert retained_stale.manager_available is False
        assert [item.name for item in result.indexers] == [
            "MAM (Prowlarr)",
            "NZBgeek (Prowlarr)",
        ]
        assert result.indexers[0].indexer_type == IndexerType.TORZNAB
        assert result.indexers[0].resolver_enabled is False
        assert result.indexers[0].categories == "7030,7040"
        assert result.indexers[1].indexer_type == IndexerType.NEWZNAB
        assert result.indexers[1].enabled is False
        assert stored_url is not None
        assert stored_url.value == "http://prowlarr:9696"
        assert stored_key is not None
        assert stored_key.value_type == "secret"
        assert decrypt_secret(stored_key.value) == "synced-key"

    async def test_resync_uses_stored_credentials_and_sync_failure_maps_to_not_found(
        self,
        sec_db: async_sessionmaker[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "pullbox.providers.indexer.prowlarr.ProwlarrIndexer",
            _FakeProwlarrIndexer,
        )
        _FakeProwlarrIndexer.remote_indexers = [
            {"id": 10, "name": "Stored", "protocol": "torrent", "priority": 5}
        ]

        async with sec_db() as session:
            session.add_all(
                [
                    SystemConfig(key="prowlarr_url", value="http://stored-prowlarr:9696"),
                    SystemConfig(
                        key="prowlarr_api_key",
                        value=encrypt_secret("stored-key"),
                        value_type="secret",
                    ),
                ]
            )
            await session.flush()

            result = await indexers_api.resync_prowlarr_indexers(object(), session)  # type: ignore[arg-type]
            assert result.added == 1
            assert _FakeProwlarrIndexer.instances[-1].api_key == "stored-key"

            _FakeProwlarrIndexer.fail_on_get = True
            with pytest.raises(NotFoundError):
                await indexers_api.sync_prowlarr_indexers(
                    ProwlarrSyncRequest(
                        prowlarr_url="http://prowlarr:9696",
                        prowlarr_api_key="bad-key",
                    ),
                    object(),  # type: ignore[arg-type]
                    session,
                )


@pytest.mark.asyncio
class TestJackettRoutes:
    async def test_jackett_connection_routes_use_inline_and_stored_credentials(
        self,
        sec_db: async_sessionmaker[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "pullbox.services.jackett_sync_service.JackettClient",
            _FakeJackettClient,
        )

        async with sec_db() as session:
            inline = await indexers_api.test_jackett_connection(
                JackettSyncRequest(
                    jackett_url="http://jackett:9117",
                    jackett_api_key="inline-key",
                ),
                object(),  # type: ignore[arg-type]
            )
            session.add_all(
                [
                    SystemConfig(key="jackett_url", value="http://stored-jackett:9117"),
                    SystemConfig(
                        key="jackett_api_key",
                        value=encrypt_secret("stored-key"),
                        value_type="secret",
                    ),
                ]
            )
            await session.flush()
            stored = await indexers_api.test_jackett_stored(object(), session)  # type: ignore[arg-type]

        assert inline["healthy"] is True
        assert stored["message"] == "Jackett is reachable"
        assert _FakeJackettClient.instances[0].api_key == "inline-key"
        assert _FakeJackettClient.instances[1].api_key == "stored-key"
        assert all(instance.closed for instance in _FakeJackettClient.instances)

    async def test_stored_jackett_routes_require_credentials(
        self,
        sec_db: async_sessionmaker[AsyncSession],
    ) -> None:
        async with sec_db() as session:
            with pytest.raises(NotFoundError):
                await indexers_api.test_jackett_stored(object(), session)  # type: ignore[arg-type]
            with pytest.raises(NotFoundError):
                await indexers_api.resync_jackett_indexers(object(), session)  # type: ignore[arg-type]

    async def test_sync_jackett_preserves_local_controls_and_retires_missing_trackers(
        self,
        sec_db: async_sessionmaker[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "pullbox.services.jackett_sync_service.JackettClient",
            _FakeJackettClient,
        )
        _FakeJackettClient.remote_indexers = [
            SimpleNamespace(
                id="1337x",
                name="1337x",
                description="Public tracker",
                categories=("7000", "7030", "8000"),
                search_modes=("search",),
            ),
            SimpleNamespace(
                id="aniRena",
                name="AniRena",
                description=None,
                categories=("5070",),
                search_modes=("search",),
            ),
        ]

        async with sec_db() as session:
            existing = await _seed_indexer(
                session,
                name="Old 1337x",
                indexer_type=IndexerType.TORZNAB,
                source="jackett",
                manager_indexer_id="1337x",
                enabled=False,
                priority=7,
                enable_rss=False,
                enable_automatic_search=False,
                enable_interactive_search=True,
            )
            stale = await _seed_indexer(
                session,
                name="Removed tracker",
                indexer_type=IndexerType.TORZNAB,
                source="jackett",
                manager_indexer_id="removed",
            )

            result = await indexers_api.sync_jackett_indexers(
                JackettSyncRequest(
                    jackett_url="http://jackett:9117/",
                    jackett_api_key="synced-key",
                ),
                object(),  # type: ignore[arg-type]
                session,
            )
            await session.refresh(existing)
            await session.refresh(stale)
            stored_url = await session.get(SystemConfig, "jackett_url")
            stored_key = await session.get(SystemConfig, "jackett_api_key")

        assert result.added == 1
        assert result.updated == 1
        assert result.retired == 1
        assert result.reactivated == 0
        assert result.total == 2
        assert [item.name for item in result.indexers] == [
            "1337x (Jackett)",
            "AniRena (Jackett)",
        ]
        assert existing.url == ("http://jackett:9117/api/v2.0/indexers/1337x/results/torznab")
        assert existing.enabled is False
        assert existing.priority == 7
        assert existing.categories == "7030"
        assert existing.enable_rss is False
        assert existing.enable_automatic_search is False
        assert existing.enable_interactive_search is True
        assert existing.resolver_enabled is False
        assert existing.manager_available is True
        assert decrypt_secret(existing.api_key) == "synced-key"
        assert stale.manager_available is False
        assert stored_url is not None
        assert stored_url.value == "http://jackett:9117"
        assert stored_key is not None
        assert stored_key.value_type == "secret"
        assert decrypt_secret(stored_key.value) == "synced-key"

    async def test_resync_reactivates_tracker_with_stored_credentials(
        self,
        sec_db: async_sessionmaker[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "pullbox.services.jackett_sync_service.JackettClient",
            _FakeJackettClient,
        )
        _FakeJackettClient.remote_indexers = [
            SimpleNamespace(
                id="1337x",
                name="1337x",
                description=None,
                categories=("7030",),
                search_modes=("search",),
            )
        ]

        async with sec_db() as session:
            retired = await _seed_indexer(
                session,
                name="1337x (Jackett)",
                indexer_type=IndexerType.TORZNAB,
                source="jackett",
                manager_indexer_id="1337x",
                manager_available=False,
            )
            session.add_all(
                [
                    SystemConfig(key="jackett_url", value="http://stored-jackett:9117"),
                    SystemConfig(
                        key="jackett_api_key",
                        value=encrypt_secret("stored-key"),
                        value_type="secret",
                    ),
                ]
            )
            await session.flush()

            result = await indexers_api.resync_jackett_indexers(object(), session)  # type: ignore[arg-type]
            await session.refresh(retired)

        assert result.added == 0
        assert result.updated == 1
        assert result.reactivated == 1
        assert retired.manager_available is True
        assert _FakeJackettClient.instances[-1].api_key == "stored-key"


@pytest.mark.asyncio
class TestIndexerConnectionRoutes:
    @pytest.mark.parametrize(
        ("indexer_type", "patch_target"),
        [
            (IndexerType.NEWZNAB, "pullbox.providers.indexer.newznab.NewznabIndexer"),
            (IndexerType.TORZNAB, "pullbox.providers.indexer.torznab.TorznabIndexer"),
            (IndexerType.PROWLARR, "pullbox.providers.indexer.prowlarr.ProwlarrIndexer"),
        ],
    )
    async def test_indexer_test_route_builds_provider_and_persists_success(
        self,
        sec_db: async_sessionmaker[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
        indexer_type: IndexerType,
        patch_target: str,
    ) -> None:
        class _FakeProvider:
            def __init__(self, **kwargs: object) -> None:
                self.kwargs = kwargs

            async def test_connection(self) -> ProviderHealthResult:
                return _health(f"{indexer_type.value} reachable")

        monkeypatch.setattr(patch_target, _FakeProvider)

        async with sec_db() as session:
            indexer = await _seed_indexer(
                session,
                name=f"{indexer_type.value} source",
                indexer_type=indexer_type,
            )
            indexer.failure_count = 5
            indexer.disabled_until = datetime.now(UTC) + timedelta(hours=6)
            indexer.last_error = "Search failed while Prowlarr restarted"

            result = await indexers_api.test_indexer(indexer.id, object(), session)  # type: ignore[arg-type]
            await session.refresh(indexer)

        assert result == {
            "healthy": True,
            "message": f"{indexer_type.value} reachable",
            "response_time_ms": 14.25,
        }
        assert indexer.last_success_at is not None
        assert indexer.last_error is None
        assert indexer.failure_count == 0
        assert indexer.disabled_until is None

    async def test_manual_torznab_test_route_uses_ranked_resolver_chain(
        self,
        sec_db: async_sessionmaker[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        options = (object(),)
        constructor_kwargs: dict[str, object] = {}
        built_for: list[int] = []

        class _FakeProvider:
            def __init__(self, **kwargs: object) -> None:
                constructor_kwargs.update(kwargs)

            async def test_connection(self) -> ProviderHealthResult:
                return _health("challenged Torznab reachable")

        async def _build_options(_session: object, indexer: IndexerConfig) -> tuple[object, ...]:
            built_for.append(indexer.id)
            return options

        monkeypatch.setattr(
            "pullbox.providers.indexer.torznab.TorznabIndexer",
            _FakeProvider,
        )
        monkeypatch.setattr(
            "pullbox.services.direct_resolver_service.build_manual_torznab_resolver_options",
            _build_options,
        )

        async with sec_db() as session:
            indexer = await _seed_indexer(
                session,
                name="Challenged Torznab",
                indexer_type=IndexerType.TORZNAB,
                resolver_enabled=True,
            )
            result = await indexers_api.test_indexer(indexer.id, object(), session)  # type: ignore[arg-type]

        assert result["healthy"] is True
        assert built_for == [indexer.id]
        assert constructor_kwargs["resolver_enabled"] is True
        assert constructor_kwargs["resolver_options"] is options

    async def test_indexer_test_route_persists_failure_and_requires_existing_indexer(
        self,
        sec_db: async_sessionmaker[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        class _FailingProvider:
            def __init__(self, **kwargs: object) -> None:
                self.kwargs = kwargs

            async def test_connection(self) -> ProviderHealthResult:
                return _health("indexer refused connection", healthy=False)

        monkeypatch.setattr("pullbox.providers.indexer.newznab.NewznabIndexer", _FailingProvider)

        async with sec_db() as session:
            indexer = await _seed_indexer(session)
            result = await indexers_api.test_indexer(indexer.id, object(), session)  # type: ignore[arg-type]
            await session.refresh(indexer)

            with pytest.raises(NotFoundError):
                await indexers_api.test_indexer(999_004, object(), session)  # type: ignore[arg-type]

        assert result["healthy"] is False
        assert indexer.last_failure_at is not None
        assert indexer.last_error == "indexer refused connection"

    async def test_indexer_test_route_retries_transient_sqlite_lock(
        self,
        sec_db: async_sessionmaker[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        class _FakeProvider:
            def __init__(self, **kwargs: object) -> None:
                self.kwargs = kwargs

            async def test_connection(self) -> ProviderHealthResult:
                return _health("indexer reachable after retry")

        monkeypatch.setattr("pullbox.providers.indexer.newznab.NewznabIndexer", _FakeProvider)

        async with sec_db() as session:
            indexer = await _seed_indexer(session)
            await session.commit()
            original_flush = session.flush
            flush_attempts = 0

            async def _flaky_flush(*args: object, **kwargs: object) -> None:
                nonlocal flush_attempts
                flush_attempts += 1
                if flush_attempts == 1:
                    raise OperationalError(
                        "UPDATE indexer_configs",
                        {},
                        sqlite3.OperationalError("database is locked"),
                    )
                await original_flush(*args, **kwargs)

            monkeypatch.setattr(session, "flush", _flaky_flush)
            monkeypatch.setattr(indexers_api.asyncio, "sleep", _instant_sleep)

            result = await indexers_api.test_indexer(indexer.id, object(), session)  # type: ignore[arg-type]
            await session.refresh(indexer)

        assert flush_attempts == 2
        assert result["healthy"] is True
        assert indexer.last_success_at is not None
        assert indexer.last_error is None
