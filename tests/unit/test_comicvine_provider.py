"""Unit tests for ComicVine provider search behavior."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from pullbox.providers.metadata.comicvine import ComicVineProvider


def _volume_item(provider_id: int, title: str, year: int) -> dict[str, object]:
    return {
        "id": provider_id,
        "name": title,
        "start_year": year,
        "publisher": {"name": "Marvel"},
        "count_of_issues": 4,
        "image": {"medium_url": f"https://example.test/{provider_id}.jpg"},
        "deck": f"{title} deck",
        "site_detail_url": f"https://comicvine.gamespot.com/example/4050-{provider_id}/",
    }


def _issue_item(provider_id: int, issue_number: str) -> dict[str, object]:
    return {
        "id": provider_id,
        "issue_number": issue_number,
        "name": f"Issue {issue_number}",
        "cover_date": "2026-06-01",
        "image": {"medium_url": f"https://example.test/issues/{provider_id}.jpg"},
    }


@pytest.mark.asyncio
async def test_search_series_globally_fetches_volume_offsets() -> None:
    provider = ComicVineProvider(api_key="offset-test-key", rate_limit=999_999)
    first_page = [
        _volume_item(1000 + index, f"Offset Test {index}", 2000 + index) for index in range(100)
    ]
    second_page = [_volume_item(2000, "Offset Test Final", 2026)]
    calls: list[tuple[str, dict[str, object]]] = []

    async def fake_request(endpoint: str, params: dict[str, object]) -> dict[str, object]:
        calls.append((endpoint, dict(params)))
        offset = int(params["offset"])
        return {
            "number_of_total_results": 101,
            "results": first_page if offset == 0 else second_page,
        }

    provider._request = AsyncMock(side_effect=fake_request)  # type: ignore[method-assign]

    try:
        results, total = await provider.search_series_globally(
            "Offset Test",
            max_results=101,
        )
    finally:
        await provider._client.aclose()

    assert total == 101
    assert len(results) == 101
    assert [call[1]["offset"] for call in calls] == [0, 100]
    assert all(call[0] == "/volumes/" for call in calls)
    assert calls[0][1]["filter"] == "name:Offset,name:Test"
    assert calls[0][1]["limit"] == 100
    assert calls[1][1]["limit"] == 1


@pytest.mark.asyncio
async def test_search_series_globally_reuses_short_lived_cache() -> None:
    provider = ComicVineProvider(api_key="cache-test-key", rate_limit=999_999)
    request_mock = AsyncMock(
        return_value={
            "number_of_total_results": 1,
            "results": [_volume_item(3000, "Cache Test", 2026)],
        }
    )
    provider._request = request_mock  # type: ignore[method-assign]

    try:
        first, first_total = await provider.search_series_globally("Cache Test", max_results=10)
        second, second_total = await provider.search_series_globally("Cache Test", max_results=10)
    finally:
        await provider._client.aclose()

    assert first_total == 1
    assert second_total == 1
    assert [result.provider_id for result in first] == ["3000"]
    assert [result.provider_id for result in second] == ["3000"]
    request_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_search_series_globally_collapses_concurrent_identical_requests() -> None:
    provider = ComicVineProvider(api_key="single-flight-test-key", rate_limit=999_999)
    request_started = asyncio.Event()
    release_request = asyncio.Event()
    request_count = 0

    async def fake_request(_endpoint: str, _params: dict[str, object]) -> dict[str, object]:
        nonlocal request_count
        request_count += 1
        request_started.set()
        await release_request.wait()
        return {
            "number_of_total_results": 1,
            "results": [_volume_item(4000, "Single Flight Test", 2026)],
        }

    provider._request = AsyncMock(side_effect=fake_request)  # type: ignore[method-assign]

    first_task = asyncio.create_task(
        provider.search_series_globally("Single Flight Test", max_results=10)
    )
    await request_started.wait()
    second_task = asyncio.create_task(
        provider.search_series_globally("single flight test", max_results=10)
    )
    await asyncio.sleep(0)
    release_request.set()

    try:
        first, second = await asyncio.gather(first_task, second_task)
    finally:
        await provider._client.aclose()

    assert request_count == 1
    assert first == second
    assert [result.provider_id for result in first[0]] == ["4000"]


@pytest.mark.asyncio
async def test_search_series_globally_shields_shared_task_from_caller_cancellation() -> None:
    provider = ComicVineProvider(api_key="shield-test-key", rate_limit=999_999)
    request_started = asyncio.Event()
    release_request = asyncio.Event()
    request_count = 0

    async def fake_request(_endpoint: str, _params: dict[str, object]) -> dict[str, object]:
        nonlocal request_count
        request_count += 1
        request_started.set()
        await release_request.wait()
        return {
            "number_of_total_results": 1,
            "results": [_volume_item(5000, "Shield Test", 2026)],
        }

    provider._request = AsyncMock(side_effect=fake_request)  # type: ignore[method-assign]

    first_task = asyncio.create_task(provider.search_series_globally("Shield Test", max_results=10))
    await request_started.wait()
    second_task = asyncio.create_task(
        provider.search_series_globally("shield test", max_results=10)
    )
    await asyncio.sleep(0)

    first_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first_task

    release_request.set()

    try:
        second_result = await second_task
        cached_result = await provider.search_series_globally("Shield Test", max_results=10)
    finally:
        await provider._client.aclose()

    assert request_count == 1
    assert [result.provider_id for result in second_result[0]] == ["5000"]
    assert [result.provider_id for result in cached_result[0]] == ["5000"]


@pytest.mark.asyncio
async def test_get_recent_issues_for_series_fetches_single_date_descending_page() -> None:
    provider = ComicVineProvider(api_key="recent-issues-test-key", rate_limit=999_999)
    request_mock = AsyncMock(
        return_value={
            "number_of_total_results": 250,
            "results": [_issue_item(9001, "250"), _issue_item(9000, "249")],
        }
    )
    provider._request = request_mock  # type: ignore[method-assign]

    try:
        summaries = await provider.get_recent_issues_for_series("12345", limit=2)
    finally:
        await provider._client.aclose()

    assert [summary.provider_id for summary in summaries] == ["9001", "9000"]
    request_mock.assert_awaited_once()
    endpoint, params = request_mock.await_args.args
    assert endpoint == "/issues/"
    assert params["filter"] == "volume:12345"
    assert params["sort"] == "store_date:desc"
    assert "store_date" in str(params["field_list"])
    assert params["limit"] == 2
    assert params["offset"] == 0
