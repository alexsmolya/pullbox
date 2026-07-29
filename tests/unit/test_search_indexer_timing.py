"""Search fan-out timing diagnostics."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from pullbox.models.indexer import IndexerConfig, IndexerType
from pullbox.providers.base import ProviderRegistry, ReleaseResult, SearchQuery
from pullbox.services.search_indexers import search_indexers

if TYPE_CHECKING:
    from pullbox.providers.base import IndexerCapabilities, ProviderHealthResult


class _FakeIndexer:
    def __init__(self, name: str, results: list[ReleaseResult]) -> None:
        self.name = name
        self._results = results

    async def search(self, query: SearchQuery) -> list[ReleaseResult]:
        return self._results

    async def capabilities(self) -> IndexerCapabilities:
        raise NotImplementedError

    async def test_connection(self) -> ProviderHealthResult:
        raise NotImplementedError


class _FailingIndexer(_FakeIndexer):
    async def search(self, query: SearchQuery) -> list[ReleaseResult]:
        raise TimeoutError(f"{self.name} timed out")


def _release(title: str, *, category: str | None = "7030") -> ReleaseResult:
    return ReleaseResult(
        title=title,
        indexer_name="FixtureIndexer",
        download_url=f"https://example.test/{title.replace(' ', '_')}",
        size_bytes=100_000_000,
        age_days=1,
        seeders=10,
        leechers=1,
        grabs=None,
        is_torrent=True,
        category=category,
        published_at=None,
    )


@pytest.mark.asyncio
async def test_search_indexers_records_per_indexer_timing_diagnostics() -> None:
    registry = ProviderRegistry()
    registry.register_indexer(
        1,
        _FakeIndexer(
            "FixtureIndexer",
            [
                _release("Absolute Flash 001 (2025).cbz"),
                _release("Absolute Flash audiobook", category="Audio"),
            ],
        ),
    )
    timings: list[dict[str, object]] = []

    results = await search_indexers(
        registry,
        SearchQuery(series_title="Absolute Flash #001", issue_number=None),
        timing_collector=timings,
    )

    assert [result.title for result in results] == ["Absolute Flash 001 (2025).cbz"]
    assert results[0].indexer_id == 1
    assert timings == [
        {
            "query": "Absolute Flash #001",
            "indexer": "FixtureIndexer",
            "status": "completed",
            "elapsed_ms": timings[0]["elapsed_ms"],
            "raw_count": 2,
            "result_count": 1,
            "filtered_count": 1,
            "categories": None,
        }
    ]
    assert isinstance(timings[0]["elapsed_ms"], int)


@pytest.mark.asyncio
async def test_search_indexers_records_failure_without_losing_healthy_results() -> None:
    registry = ProviderRegistry()
    registry.register_indexer(1, _FailingIndexer("UnavailableIndexer", []))
    registry.register_indexer(
        2,
        _FakeIndexer("HealthyIndexer", [_release("Absolute Flash 001 (2025).cbz")]),
    )
    failed_config = IndexerConfig(
        name="UnavailableIndexer",
        indexer_type=IndexerType.PROWLARR,
        url="https://unavailable.example.test",
        api_key="encrypted",
        failure_count=0,
    )
    healthy_config = IndexerConfig(
        name="HealthyIndexer",
        indexer_type=IndexerType.PROWLARR,
        url="https://healthy.example.test",
        api_key="encrypted",
        failure_count=2,
    )
    timings: list[dict[str, object]] = []

    results = await search_indexers(
        registry,
        SearchQuery(series_title="Absolute Flash #001", issue_number=None),
        indexer_configs={1: failed_config, 2: healthy_config},
        timing_collector=timings,
    )

    assert [result.title for result in results] == ["Absolute Flash 001 (2025).cbz"]
    assert [timing["status"] for timing in timings] == ["failed", "completed"]
    assert timings[0]["error"] == "UnavailableIndexer timed out"
    assert failed_config.failure_count == 1
    assert failed_config.last_failure_at is not None
    assert healthy_config.failure_count == 0
    assert healthy_config.last_success_at is not None


@pytest.mark.asyncio
async def test_manual_search_ignores_backoff_and_restores_indexer_health() -> None:
    registry = ProviderRegistry()
    indexer = _FakeIndexer(
        "NZBgeek",
        [_release("Infernal Hulk 001 [2026] [Digital].cbz")],
    )
    registry.register_indexer(1, indexer)
    config = IndexerConfig(
        name="NZBgeek",
        indexer_type=IndexerType.NEWZNAB,
        url="https://prowlarr.test/15",
        api_key="encrypted",
        failure_count=5,
    )
    config.disabled_until = datetime.now(UTC) + timedelta(hours=2)
    config.last_error = "Prowlarr restarted"

    results = await search_indexers(
        registry,
        SearchQuery(series_title="Infernal Hulk", issue_number=1),
        indexer_configs={1: config},
        ignore_backoff=True,
    )

    assert [result.title for result in results] == ["Infernal Hulk 001 [2026] [Digital].cbz"]
    assert config.failure_count == 0
    assert config.disabled_until is None
    assert config.last_error is None
