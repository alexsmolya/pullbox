"""Focused coverage for shared issue-search helpers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from pullbox.api.v1 import issues as issues_api
from pullbox.models import Base
from pullbox.models.issue import Issue, IssueStatus, IssueType
from pullbox.models.library import MatchConfidence
from pullbox.models.search_log import SearchType
from pullbox.models.series import Series, SeriesStatus, SeriesType
from pullbox.providers.base import ProviderRegistry, ReleaseResult
from pullbox.services.search_service import IssueSearchOutcome, IssueSearchTarget, SearchRuntime

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


def _make_release(title: str = "Absolute Superman 009") -> ReleaseResult:
    return ReleaseResult(
        title=title,
        indexer_name="NZBgeek",
        download_url=f"https://example.com/{title.replace(' ', '_')}",
        size_bytes=100_000_000,
        age_days=3,
        seeders=None,
        leechers=None,
        grabs=25,
        is_torrent=False,
        category="7030",
        published_at=None,
    )


@pytest.fixture
async def db_factory() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _create_issue(factory: async_sessionmaker[AsyncSession]) -> int:
    async with factory() as session:
        series = Series(
            comicvine_id=801,
            title="Absolute Superman",
            sort_title="absolute superman",
            year_start=2025,
            status=SeriesStatus.CONTINUING,
            series_type=SeriesType.STANDARD,
            monitored=True,
            issue_count=1,
        )
        session.add(series)
        await session.flush()
        issue = Issue(
            series_id=series.id,
            comicvine_id=9001,
            issue_number=9.0,
            title="Issue #9",
            status=IssueStatus.WANTED,
            issue_type=IssueType.ISSUE,
        )
        session.add(issue)
        await session.commit()
        return issue.id


@pytest.mark.asyncio
async def test_run_issue_search_handles_not_found_and_no_runtime(
    db_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with db_factory() as session:
        with pytest.raises(issues_api.NotFoundError):
            await issues_api._run_issue_search(session, 99999, include_download_clients=False)

    issue_id = await _create_issue(db_factory)
    monkeypatch.setattr(issues_api, "build_search_runtime", AsyncMock(return_value=None))

    async with db_factory() as session:
        bundle = await issues_api._run_issue_search(
            session,
            issue_id,
            include_download_clients=False,
        )

    assert bundle.runtime is None
    assert bundle.outcome is None
    assert bundle.matched_items == []
    assert bundle.rejected_items == []


@pytest.mark.asyncio
async def test_run_issue_search_returns_shared_bundle_and_log(
    db_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issue_id = await _create_issue(db_factory)
    target = IssueSearchTarget(
        issue_id=issue_id,
        series_id=51,
        series_title="Absolute Superman",
        issue_number=9.0,
        issue_type=IssueType.ISSUE,
        issue_title="Issue #9",
        series_year=2025,
    )
    release = _make_release()
    validation = SimpleNamespace(release=release, confidence=MatchConfidence.HIGH)
    outcome = IssueSearchOutcome(
        target=target,
        mode="deep",
        query_count=2,
        raw_results=[release],
        filtered_results=[release],
        matched=[validation],
        rejected=[],
        best_release=release,
        best_validation=validation,
        search_details={"results_count": 1, "query_count": 2},
        elapsed_ms=12,
        used_fallback=True,
    )
    runtime = SearchRuntime(
        registry=ProviderRegistry(),
        indexer_configs={},
        source_priority=["NZBgeek"],
        eval_kwargs={},
        validator_kwargs={},
        type_thresholds={"issue": "high"},
        failure_threshold=3,
    )
    matched_items = [SimpleNamespace(title=release.title)]
    rejected_items = [SimpleNamespace(title="Rejected release")]

    monkeypatch.setattr(issues_api, "load_issue_search_target", AsyncMock(return_value=target))
    monkeypatch.setattr(issues_api, "build_search_runtime", AsyncMock(return_value=runtime))
    monkeypatch.setattr(
        issues_api.SearchService,
        "search_issue_target",
        AsyncMock(return_value=outcome),
    )
    monkeypatch.setattr(
        issues_api,
        "build_interactive_results",
        lambda matched, rejected, eval_kwargs, **kwargs: (
            matched_items,
            rejected_items,
        ),
    )

    async with db_factory() as session:
        bundle = await issues_api._run_issue_search(
            session,
            issue_id,
            include_download_clients=True,
        )

    assert bundle.runtime is runtime
    assert bundle.outcome is outcome
    assert bundle.matched_items == matched_items
    assert bundle.rejected_items == rejected_items

    search_log = issues_api._build_issue_search_log(bundle)
    assert search_log.search_type == SearchType.MANUAL
    assert search_log.results_found == 1
    assert search_log.results_rejected == 1
    assert search_log.best_confidence == MatchConfidence.HIGH.value

    empty_log = issues_api._build_issue_search_log(
        issues_api._IssueSearchBundle(
            target=target,
            issue=bundle.issue,
            runtime=None,
            outcome=None,
            matched_items=[],
            rejected_items=[],
            search_time_ms=0,
        )
    )
    assert empty_log.results_found == 0
    assert empty_log.details["validated_count"] == 0


@pytest.mark.asyncio
async def test_run_issue_search_releases_transactions_between_manual_search_passes(
    db_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issue_id = await _create_issue(db_factory)
    target = IssueSearchTarget(
        issue_id=issue_id,
        series_id=51,
        series_title="Absolute Superman",
        issue_number=9.0,
        issue_type=IssueType.ISSUE,
        issue_title="Issue #9",
        series_year=2025,
    )
    release = _make_release()
    validation = SimpleNamespace(release=release, confidence=MatchConfidence.HIGH)
    fast_outcome = IssueSearchOutcome(
        target=target,
        mode="fast",
        query_count=1,
        raw_results=[],
        filtered_results=[],
        matched=[],
        rejected=[],
        best_release=None,
        best_validation=None,
        search_details={"search_mode": "fast"},
        elapsed_ms=10,
    )
    runtime = SearchRuntime(
        registry=ProviderRegistry(),
        indexer_configs={},
        source_priority=None,
        eval_kwargs={},
        validator_kwargs={},
        type_thresholds={"issue": "high"},
        failure_threshold=3,
    )
    transaction_open_when_search_started: list[bool] = []

    async def search_issue_target(
        _self,
        session: AsyncSession,
        _target: IssueSearchTarget,
        *,
        mode: str,
        **_kwargs,
    ) -> IssueSearchOutcome:
        transaction_open_when_search_started.append(session.in_transaction())
        await session.execute(select(Issue.id).limit(1))
        if mode == "fast":
            return fast_outcome
        return IssueSearchOutcome(
            target=target,
            mode="deep",
            query_count=1,
            raw_results=[release],
            filtered_results=[release],
            matched=[validation],
            rejected=[],
            best_release=release,
            best_validation=validation,
            search_details={"search_mode": "deep"},
            elapsed_ms=12,
        )

    monkeypatch.setattr(issues_api, "load_issue_search_target", AsyncMock(return_value=target))
    monkeypatch.setattr(issues_api, "build_search_runtime", AsyncMock(return_value=runtime))
    monkeypatch.setattr(
        issues_api.SearchService,
        "search_issue_target",
        search_issue_target,
    )
    monkeypatch.setattr(
        issues_api,
        "build_interactive_results",
        lambda matched, rejected, eval_kwargs, **kwargs: (
            [SimpleNamespace(title=release.title)],
            [],
        ),
    )

    async with db_factory() as session:
        await issues_api._run_issue_search(
            session,
            issue_id,
            include_download_clients=False,
        )

    assert transaction_open_when_search_started == [False, False]


@pytest.mark.asyncio
async def test_run_issue_search_uses_fast_manual_search_when_it_finds_matches(
    db_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issue_id = await _create_issue(db_factory)
    target = IssueSearchTarget(
        issue_id=issue_id,
        series_id=51,
        series_title="Absolute Superman",
        issue_number=9.0,
        issue_type=IssueType.ISSUE,
        issue_title="Issue #9",
        series_year=2025,
    )
    release = _make_release()
    validation = SimpleNamespace(release=release, confidence=MatchConfidence.HIGH)
    fast_outcome = IssueSearchOutcome(
        target=target,
        mode="fast",
        query_count=5,
        raw_results=[release],
        filtered_results=[release],
        matched=[validation],
        rejected=[],
        best_release=release,
        best_validation=validation,
        search_details={"search_mode": "fast"},
        elapsed_ms=8,
    )
    runtime = SearchRuntime(
        registry=ProviderRegistry(),
        indexer_configs={},
        source_priority=None,
        eval_kwargs={},
        validator_kwargs={},
        type_thresholds={"issue": "high"},
        failure_threshold=3,
    )
    search_mock = AsyncMock(return_value=fast_outcome)

    monkeypatch.setattr(issues_api, "load_issue_search_target", AsyncMock(return_value=target))
    monkeypatch.setattr(issues_api, "build_search_runtime", AsyncMock(return_value=runtime))
    monkeypatch.setattr(issues_api.SearchService, "search_issue_target", search_mock)
    monkeypatch.setattr(
        issues_api,
        "build_interactive_results",
        lambda matched, rejected, eval_kwargs, **kwargs: (
            [SimpleNamespace(title=release.title)],
            [],
        ),
    )

    async with db_factory() as session:
        bundle = await issues_api._run_issue_search(
            session,
            issue_id,
            include_download_clients=False,
        )

    assert bundle.outcome is fast_outcome
    assert search_mock.await_count == 1
    assert search_mock.await_args.kwargs["mode"] == "fast"
    assert bundle.outcome.search_details["manual_search_strategy"] == "quick_first"


@pytest.mark.asyncio
async def test_run_issue_search_falls_back_to_deep_when_fast_has_no_matches(
    db_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issue_id = await _create_issue(db_factory)
    target = IssueSearchTarget(
        issue_id=issue_id,
        series_id=51,
        series_title="Absolute Superman",
        issue_number=9.0,
        issue_type=IssueType.ISSUE,
        issue_title="Issue #9",
        series_year=2025,
    )
    release = _make_release()
    validation = SimpleNamespace(release=release, confidence=MatchConfidence.HIGH)
    fast_outcome = IssueSearchOutcome(
        target=target,
        mode="fast",
        query_count=5,
        raw_results=[],
        filtered_results=[],
        matched=[],
        rejected=[],
        best_release=None,
        best_validation=None,
        search_details={"search_mode": "fast", "query_count": 5},
        elapsed_ms=7,
    )
    deep_outcome = IssueSearchOutcome(
        target=target,
        mode="deep",
        query_count=6,
        raw_results=[release],
        filtered_results=[release],
        matched=[validation],
        rejected=[],
        best_release=release,
        best_validation=validation,
        search_details={"search_mode": "deep", "query_count": 6},
        elapsed_ms=22,
    )
    runtime = SearchRuntime(
        registry=ProviderRegistry(),
        indexer_configs={},
        source_priority=None,
        eval_kwargs={},
        validator_kwargs={},
        type_thresholds={"issue": "high"},
        failure_threshold=3,
    )
    search_mock = AsyncMock(side_effect=[fast_outcome, deep_outcome])

    monkeypatch.setattr(issues_api, "load_issue_search_target", AsyncMock(return_value=target))
    monkeypatch.setattr(issues_api, "build_search_runtime", AsyncMock(return_value=runtime))
    monkeypatch.setattr(issues_api.SearchService, "search_issue_target", search_mock)
    monkeypatch.setattr(
        issues_api,
        "build_interactive_results",
        lambda matched, rejected, eval_kwargs, **kwargs: (
            [SimpleNamespace(title=release.title)],
            [],
        ),
    )

    async with db_factory() as session:
        bundle = await issues_api._run_issue_search(
            session,
            issue_id,
            include_download_clients=False,
        )

    assert bundle.outcome is deep_outcome
    assert search_mock.await_count == 2
    assert [call.kwargs["mode"] for call in search_mock.await_args_list] == ["fast", "deep"]
    assert bundle.outcome.search_details["manual_search_strategy"] == "quick_first_deep_fallback"
    assert bundle.outcome.search_details["fast_search"] == {
        "query_count": 5,
        "results_count": 0,
        "matched_count": 0,
        "rejected_count": 0,
        "elapsed_ms": 7,
    }
