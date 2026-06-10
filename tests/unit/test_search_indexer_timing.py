"""Search fan-out timing diagnostics."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

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
