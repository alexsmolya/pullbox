"""Direct route-function coverage for search API contracts."""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from pullbox.api.v1 import search as search_api
from pullbox.core.exceptions import NotFoundError
from pullbox.models.issue import Issue
from pullbox.models.library import FileFormat, LibraryFile, LibraryRoot, MatchConfidence
from pullbox.models.search_log import SearchLog, SearchType
from pullbox.models.series import Series
from pullbox.providers.base import ReleaseResult
from pullbox.providers.base import SeriesSearchResult as ProviderSeriesSearchResult

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytest_plugins = ["conftest_security"]


async def _seed_issue(session: AsyncSession) -> Issue:
    series = Series(title="Batman", sort_title="batman")
    session.add(series)
    await session.flush()

    issue = Issue(series_id=series.id, issue_number=1.0, title="First Night")
    session.add(issue)
    await session.flush()
    return issue


@pytest.mark.asyncio
class TestSearchSeriesRouteFunction:
    async def test_marks_existing_comicvine_results_as_already_added(
        self,
        sec_db: async_sessionmaker[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def _api_key(_session: AsyncSession) -> str:
            return "comicvine-key"

        class FakeComicVineProvider:
            def __init__(self, *, api_key: str) -> None:
                self.api_key = api_key

            async def search_series(
                self,
                query: str,
                year: int | None = None,
            ) -> list[ProviderSeriesSearchResult]:
                assert self.api_key == "comicvine-key"
                assert query == "Batman"
                assert year == 2026
                return [
                    ProviderSeriesSearchResult(
                        provider_id="101",
                        title="Batman",
                        year_start=2026,
                        publisher="DC",
                        issue_count=12,
                        status="continuing",
                        cover_url="https://example.com/batman.jpg",
                        description="The main series.",
                        comicvine_url="https://comicvine.gamespot.com/batman/4050-101/",
                    ),
                    ProviderSeriesSearchResult(
                        provider_id="202",
                        title="Batman Beyond",
                        year_start=2026,
                        publisher="DC",
                        issue_count=6,
                        status="continuing",
                        cover_url=None,
                        description=None,
                        comicvine_url=None,
                    ),
                ]

        monkeypatch.setattr("pullbox.core.comicvine_key.get_comicvine_api_key", _api_key)
        monkeypatch.setattr(
            "pullbox.providers.metadata.comicvine.ComicVineProvider",
            FakeComicVineProvider,
        )

        async with sec_db() as session:
            session.add(Series(comicvine_id=101, title="Batman", sort_title="batman"))
            await session.flush()

            results = await search_api.search_series(
                object(),  # type: ignore[arg-type]
                session,
                q="Batman",
                year=2026,
            )

        assert [result.comicvine_id for result in results] == [101, 202]
        assert results[0].already_added is True
        assert results[0].publisher_name == "DC"
        assert results[0].comicvine_url is None
        assert results[1].already_added is False


@pytest.mark.asyncio
class TestReleaseSearchRouteFunction:
    async def test_returns_empty_when_search_runtime_is_not_available(
        self,
        sec_db: async_sessionmaker[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def _no_runtime(
            _session: AsyncSession,
            *,
            include_download_clients: bool,
        ) -> None:
            assert include_download_clients is False
            return None

        monkeypatch.setattr("pullbox.services.search_service.build_search_runtime", _no_runtime)

        async with sec_db() as session:
            results = await search_api.search_releases(
                object(),  # type: ignore[arg-type]
                session,
                series="Absolute Superman",
            )

        assert results == []

    async def test_maps_release_results_from_shared_search_runtime(
        self,
        sec_db: async_sessionmaker[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        runtime = SimpleNamespace(
            registry=object(),
            failure_threshold=3,
            indexer_configs={7: object()},
        )

        async def _runtime(
            _session: AsyncSession,
            *,
            include_download_clients: bool,
        ) -> SimpleNamespace:
            assert include_download_clients is False
            return runtime

        class FakeSearchService:
            def __init__(self, *, registry: object, failure_threshold: int) -> None:
                assert registry is runtime.registry
                assert failure_threshold == 3

            async def search(
                self,
                query: Any,
                *,
                indexer_configs: dict[int, object],
            ) -> list[ReleaseResult]:
                assert indexer_configs == runtime.indexer_configs
                assert query.series_title == "Absolute Superman"
                assert query.issue_number == 9
                assert query.year == 2025
                return [
                    ReleaseResult(
                        title="Absolute Superman 009",
                        indexer_name="NZBgeek",
                        download_url="https://example.com/absolute-superman-009",
                        size_bytes=123_456,
                        age_days=2,
                        seeders=10,
                        leechers=1,
                        grabs=4,
                        is_torrent=True,
                        category="7030",
                        published_at=datetime(2026, 6, 1, tzinfo=UTC),
                    )
                ]

        monkeypatch.setattr("pullbox.services.search_service.build_search_runtime", _runtime)
        monkeypatch.setattr("pullbox.services.search_service.SearchService", FakeSearchService)

        async with sec_db() as session:
            results = await search_api.search_releases(
                object(),  # type: ignore[arg-type]
                session,
                series="Absolute Superman",
                issue=9,
                year=2025,
            )

        assert len(results) == 1
        assert results[0].title == "Absolute Superman 009"
        assert results[0].publish_date is not None
        assert results[0].publish_date.isoformat() == "2026-06-01"
        assert results[0].seeders == 10


@pytest.mark.asyncio
class TestLibrarySearchRouteFunction:
    async def test_searches_file_name_and_parsed_series_with_match_status(
        self,
        sec_db: async_sessionmaker[AsyncSession],
    ) -> None:
        async with sec_db() as session:
            root = LibraryRoot(name="Main", path="/comics")
            session.add(root)
            await session.flush()

            session.add_all(
                [
                    LibraryFile(
                        file_path="/comics/Batman/Batman 001.cbz",
                        file_name="Batman 001.cbz",
                        file_size=1_000,
                        file_format=FileFormat.CBZ,
                        file_modified_at=datetime(2026, 6, 1, tzinfo=UTC),
                        match_confidence=MatchConfidence.HIGH,
                        parsed_series="Batman",
                        parsed_issue_number=1.0,
                        library_root_id=root.id,
                    ),
                    LibraryFile(
                        file_path="/comics/Loose/Detective Batman.cbr",
                        file_name="Detective Batman.cbr",
                        file_size=2_000,
                        file_format=FileFormat.CBR,
                        file_modified_at=datetime(2026, 6, 2, tzinfo=UTC),
                        match_confidence=MatchConfidence.UNMATCHED,
                        parsed_series="Detective Comics",
                        parsed_issue_number=None,
                        library_root_id=root.id,
                    ),
                    LibraryFile(
                        file_path="/comics/Superman/Superman 001.cbz",
                        file_name="Superman 001.cbz",
                        file_size=3_000,
                        file_format=FileFormat.CBZ,
                        file_modified_at=datetime(2026, 6, 3, tzinfo=UTC),
                        match_confidence=MatchConfidence.HIGH,
                        parsed_series="Superman",
                        parsed_issue_number=1.0,
                        library_root_id=root.id,
                    ),
                ]
            )
            await session.flush()

            results = await search_api.search_library(
                object(),  # type: ignore[arg-type]
                session,
                q="batman",
                limit=10,
            )

        assert [result.file_name for result in results] == [
            "Batman 001.cbz",
            "Detective Batman.cbr",
        ]
        assert results[0].series_title == "Batman"
        assert results[0].issue_number == 1.0
        assert results[0].matched is True
        assert results[1].matched is False


@pytest.mark.asyncio
class TestSearchHistoryRouteFunctions:
    async def test_delete_existing_and_missing_search_history_entry(
        self,
        sec_db: async_sessionmaker[AsyncSession],
    ) -> None:
        async with sec_db() as session:
            issue = await _seed_issue(session)
            log = SearchLog(
                issue_id=issue.id,
                series_title="Batman",
                issue_number=1.0,
                search_type=SearchType.MANUAL,
                results_found=4,
            )
            session.add(log)
            await session.flush()
            log_id = log.id

            response = await search_api.delete_search_history_entry(
                log_id,
                object(),  # type: ignore[arg-type]
                session,
            )
            assert response.status_code == 204
            assert await session.get(SearchLog, log_id) is None

            with pytest.raises(NotFoundError):
                await search_api.delete_search_history_entry(
                    log_id,
                    object(),  # type: ignore[arg-type]
                    session,
                )

    async def test_clear_search_history_reports_deleted_count(
        self,
        sec_db: async_sessionmaker[AsyncSession],
    ) -> None:
        async with sec_db() as session:
            issue = await _seed_issue(session)
            session.add_all(
                [
                    SearchLog(
                        issue_id=issue.id,
                        series_title="Batman",
                        issue_number=1.0,
                        search_type=SearchType.MANUAL,
                    ),
                    SearchLog(
                        issue_id=issue.id,
                        series_title="Batman",
                        issue_number=2.0,
                        search_type=SearchType.AUTOMATED,
                    ),
                ]
            )
            await session.flush()

            first = await search_api.clear_search_history(
                object(),  # type: ignore[arg-type]
                session,
            )
            second = await search_api.clear_search_history(
                object(),  # type: ignore[arg-type]
                session,
            )

        assert first.deleted == 2
        assert second.deleted == 0
