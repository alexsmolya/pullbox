"""Unit tests for import ComicVine search/retry helpers."""

from __future__ import annotations

import httpx
import pytest

import pullbox.services.import_cv_search as import_cv_search
from pullbox.core.exceptions import ImportProviderDegradedError
from pullbox.providers.base import SeriesSearchResult
from pullbox.services.import_cv_search import search_with_retry


def _make_result(
    *,
    provider_id: str,
    title: str,
    year_start: int | None = 2026,
    issue_count: int | None = 1,
) -> SeriesSearchResult:
    return SeriesSearchResult(
        provider_id=provider_id,
        title=title,
        year_start=year_start,
        publisher="DC Comics",
        issue_count=issue_count,
        status="Ongoing",
        cover_url=None,
        description=None,
    )


class _GlobalSearchProvider:
    def __init__(
        self,
        *,
        global_results: list[SeriesSearchResult] | None = None,
        page_results: list[SeriesSearchResult] | None = None,
    ) -> None:
        self.global_results = global_results or []
        self.page_results = page_results or []
        self.global_calls = 0
        self.page_calls = 0

    async def search_series_globally(
        self,
        _query: str,
        *,
        max_results: int = 1000,
        suppress_errors: bool = True,
    ) -> tuple[list[SeriesSearchResult], int]:
        self.global_calls += 1
        return self.global_results[:max_results], len(self.global_results)

    async def search_series(
        self,
        _query: str,
        _year: int | None = None,
        *,
        limit: int = 20,
        suppress_errors: bool = True,
    ) -> list[SeriesSearchResult]:
        self.page_calls += 1
        return self.page_results[:limit]


@pytest.mark.asyncio
async def test_global_compact_exact_result_skips_page_search() -> None:
    provider = _GlobalSearchProvider(
        global_results=[
            _make_result(provider_id="19752", title="2000 AD", issue_count=2484),
        ],
        page_results=[
            _make_result(provider_id="165612", title="Best of 2000AD"),
        ],
    )

    results = await search_with_retry(provider, "2000AD", 2026)

    assert [result.provider_id for result in results] == ["19752"]
    assert provider.global_calls == 1
    assert provider.page_calls == 0


@pytest.mark.asyncio
async def test_global_miss_merges_page_results_without_duplicate_ids() -> None:
    global_only = _make_result(provider_id="165612", title="Best of 2000AD")
    duplicate = _make_result(provider_id="19752", title="2000 AD", issue_count=2484)
    provider = _GlobalSearchProvider(
        global_results=[global_only, duplicate],
        page_results=[duplicate, _make_result(provider_id="999", title="2000 AD Regened")],
    )

    results = await search_with_retry(provider, "2000AD prog", 2026)

    assert [result.provider_id for result in results] == ["165612", "19752", "999"]
    assert provider.global_calls == 1
    assert provider.page_calls == 1


@pytest.mark.asyncio
async def test_persistent_timeout_raises_provider_degraded(monkeypatch) -> None:
    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(import_cv_search.asyncio, "sleep", _no_sleep)

    class TimeoutProvider:
        async def search_series(
            self,
            _query: str,
            _year: int | None = None,
            **_kwargs: object,
        ) -> list[SeriesSearchResult]:
            raise httpx.TimeoutException("slow")

    with pytest.raises(ImportProviderDegradedError) as exc_info:
        await search_with_retry(TimeoutProvider(), "Batman", 2026)

    assert exc_info.value.provider == "comicvine"
    assert exc_info.value.query == "Batman"
    assert exc_info.value.attempts == 3
