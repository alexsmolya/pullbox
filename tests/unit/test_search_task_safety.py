"""Automated search safety contracts."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from pullbox.models import Base
from pullbox.models.config import SystemConfig
from pullbox.models.issue import Issue, IssueStatus, IssueType
from pullbox.models.library import MatchConfidence
from pullbox.models.search_log import SearchLog, SearchType
from pullbox.models.series import Series, SeriesStatus, SeriesType
from pullbox.providers.base import ProviderRegistry, ReleaseResult
from pullbox.services.search_service import (
    IssueSearchOutcome,
    IssueSearchTarget,
    SearchRuntime,
    SearchService,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


@pytest.fixture
async def db_factory() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _seed_issue(
    factory: async_sessionmaker[AsyncSession],
    *,
    issue_type: IssueType,
    comicvine_id: int = 901,
) -> IssueSearchTarget:
    async with factory() as session:
        series = Series(
            comicvine_id=comicvine_id,
            title="Absolute Flash",
            sort_title="absolute flash",
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
            comicvine_id=comicvine_id + 9000,
            issue_number=1.0,
            title="Issue #1",
            status=IssueStatus.WANTED,
            issue_type=issue_type,
        )
        session.add(issue)
        await session.commit()
        return IssueSearchTarget(
            issue_id=issue.id,
            series_id=series.id,
            series_title=series.title,
            issue_number=issue.issue_number,
            issue_type=issue_type,
            issue_title=issue.title,
            series_year=series.year_start,
        )


def _release(title: str = "Absolute Flash #001 (2025).cbz") -> ReleaseResult:
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
        category="7030",
        published_at=None,
    )


def _outcome(
    target: IssueSearchTarget,
    *,
    confidence: MatchConfidence,
) -> IssueSearchOutcome:
    release = _release()
    validation = SimpleNamespace(release=release, confidence=confidence)
    return IssueSearchOutcome(
        target=target,
        mode="fast",
        query_count=1,
        raw_results=[release],
        filtered_results=[release],
        matched=[validation],
        rejected=[],
        best_release=release,
        best_validation=validation,
        search_details={"search_mode": "fast"},
        elapsed_ms=5,
    )


def _no_result_outcome(target: IssueSearchTarget) -> IssueSearchOutcome:
    return IssueSearchOutcome(
        target=target,
        mode="fast",
        query_count=5,
        raw_results=[],
        filtered_results=[],
        matched=[],
        rejected=[],
        best_release=None,
        best_validation=None,
        search_details={"results_count": 0, "query_count": 5},
        elapsed_ms=10,
    )


@pytest.mark.asyncio
async def test_search_wanted_uses_bounded_fast_search_not_deep_manual_fanout(
    db_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wanted sweeps should use the bounded shared quick-first batch strategy."""
    from pullbox.tasks import search_task

    target = await _seed_issue(db_factory, issue_type=IssueType.ISSUE, comicvine_id=949)
    runtime = SearchRuntime(
        registry=ProviderRegistry(),
        indexer_configs={},
        source_priority=None,
        eval_kwargs={},
        validator_kwargs={},
        type_thresholds={"issue": "high"},
        failure_threshold=3,
    )
    search_targets_quick_first = AsyncMock(return_value=[])

    monkeypatch.setattr(search_task, "get_session_factory", lambda: db_factory)
    monkeypatch.setattr(
        search_task,
        "_build_task_search_runtime",
        AsyncMock(return_value=runtime),
    )
    monkeypatch.setattr(
        search_task,
        "load_wanted_issue_search_targets",
        AsyncMock(return_value=[target]),
    )
    monkeypatch.setattr(
        SearchService,
        "search_targets_quick_first",
        search_targets_quick_first,
    )

    await search_task.search_wanted()

    search_targets_quick_first.assert_awaited_once()
    assert search_targets_quick_first.await_args.kwargs["concurrency"] == 1
    assert search_targets_quick_first.await_args.kwargs["enable_deep_fallback"] is True


@pytest.mark.asyncio
async def test_manual_search_wanted_run_ignores_indexer_backoff(
    db_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pressing Run on Search Wanted must make a real indexer attempt."""
    from pullbox.tasks import search_task

    target = await _seed_issue(db_factory, issue_type=IssueType.ISSUE, comicvine_id=950)
    runtime = SearchRuntime(
        registry=ProviderRegistry(),
        indexer_configs={},
        source_priority=None,
        eval_kwargs={},
        validator_kwargs={},
        type_thresholds={"issue": "high"},
        failure_threshold=3,
    )
    ignore_backoff_values: list[bool] = []

    class _CapturingSearchService(SearchService):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)  # type: ignore[arg-type]
            ignore_backoff_values.append(self._ignore_indexer_backoff)

        async def search_targets_quick_first(self, *args: object, **kwargs: object):
            return [_no_result_outcome(target)]

    monkeypatch.setattr(search_task, "get_session_factory", lambda: db_factory)
    monkeypatch.setattr(search_task, "get_current_task_trigger_type", lambda: "manual")
    monkeypatch.setattr(
        search_task,
        "_build_task_search_runtime",
        AsyncMock(return_value=runtime),
    )
    monkeypatch.setattr(
        search_task,
        "load_wanted_issue_search_targets",
        AsyncMock(return_value=[target]),
    )
    monkeypatch.setattr(search_task, "SearchService", _CapturingSearchService)

    await search_task.search_wanted()

    assert ignore_backoff_values == [True]


@pytest.mark.asyncio
async def test_search_wanted_persists_running_history_before_network_completion(
    db_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Search History must prove a wanted sweep is active while an indexer is slow."""
    from pullbox.tasks import search_task

    target = await _seed_issue(db_factory, issue_type=IssueType.ISSUE, comicvine_id=951)
    runtime = SearchRuntime(
        registry=ProviderRegistry(),
        indexer_configs={},
        source_priority=None,
        eval_kwargs={},
        validator_kwargs={},
        type_thresholds={"issue": "high"},
        failure_threshold=3,
    )
    search_started = asyncio.Event()
    release_search = asyncio.Event()

    async def _slow_search(*args: object, **kwargs: object) -> list[IssueSearchOutcome]:
        search_started.set()
        await release_search.wait()
        return [_no_result_outcome(target)]

    monkeypatch.setattr(search_task, "get_session_factory", lambda: db_factory)
    monkeypatch.setattr(
        search_task,
        "_build_task_search_runtime",
        AsyncMock(return_value=runtime),
    )
    monkeypatch.setattr(
        search_task,
        "load_wanted_issue_search_targets",
        AsyncMock(return_value=[target]),
    )
    monkeypatch.setattr(
        SearchService,
        "search_targets_quick_first",
        _slow_search,
    )

    task = asyncio.create_task(search_task.search_wanted())
    try:
        await asyncio.wait_for(search_started.wait(), timeout=1)
        async with db_factory() as session:
            logs = list((await session.execute(select(SearchLog))).scalars())

        assert len(logs) == 1
        assert logs[0].search_type == SearchType.AUTOMATED
        assert logs[0].details["run_state"] == "running"
        assert logs[0].details["action_status"] == "searching"
    finally:
        release_search.set()
        await task


@pytest.mark.asyncio
async def test_search_wanted_routes_and_finalizes_each_outcome_before_batch_returns(
    db_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Completed issue searches must not wait behind the rest of the 50-item batch."""
    from pullbox.tasks import search_task

    first = await _seed_issue(db_factory, issue_type=IssueType.ISSUE, comicvine_id=952)
    second = await _seed_issue(db_factory, issue_type=IssueType.ISSUE, comicvine_id=953)
    runtime = SearchRuntime(
        registry=ProviderRegistry(),
        indexer_configs={},
        source_priority=None,
        eval_kwargs={},
        validator_kwargs={},
        type_thresholds={"issue": "high"},
        failure_threshold=3,
    )
    first_outcome = _outcome(first, confidence=MatchConfidence.HIGH)
    second_outcome = _no_result_outcome(second)
    event_order: list[str] = []

    async def _progressive_search(
        *args: object,
        on_outcome=None,
        **kwargs: object,
    ) -> list[IssueSearchOutcome]:
        if on_outcome is not None:
            await on_outcome(first_outcome)
            event_order.append("first_callback_complete")
            await on_outcome(second_outcome)
        event_order.append("batch_returned")
        return [first_outcome, second_outcome]

    download_svc = AsyncMock()
    download_svc.send_to_client = AsyncMock(
        side_effect=lambda *args, **kwargs: event_order.append("first_routed")
    )
    intervention_svc = AsyncMock()
    intervention_svc.has_pending_for_issue = AsyncMock(return_value=False)

    monkeypatch.setattr(search_task, "get_session_factory", lambda: db_factory)
    monkeypatch.setattr(
        search_task,
        "_build_task_search_runtime",
        AsyncMock(return_value=runtime),
    )
    monkeypatch.setattr(
        search_task,
        "load_wanted_issue_search_targets",
        AsyncMock(return_value=[first, second]),
    )
    monkeypatch.setattr(
        SearchService,
        "search_targets_quick_first",
        _progressive_search,
    )
    monkeypatch.setattr(search_task, "_build_download_service", lambda registry: download_svc)
    monkeypatch.setattr(
        search_task,
        "InterventionService",
        lambda download_service: intervention_svc,
    )

    await search_task.search_wanted()

    assert event_order.index("first_routed") < event_order.index("batch_returned")
    download_svc.send_to_client.assert_awaited_once()
    async with db_factory() as session:
        logs = list(
            (await session.execute(select(SearchLog).order_by(SearchLog.issue_id))).scalars()
        )

    assert len(logs) == 2
    assert all(log.details["run_state"] == "completed" for log in logs)


@pytest.mark.asyncio
async def test_search_wanted_marks_unfinished_rows_failed_after_fanout_error(
    db_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider failure must not leave untouched history rows running forever."""
    from pullbox.tasks import search_task

    first = await _seed_issue(db_factory, issue_type=IssueType.ISSUE, comicvine_id=954)
    second = await _seed_issue(db_factory, issue_type=IssueType.ISSUE, comicvine_id=955)
    runtime = SearchRuntime(
        registry=ProviderRegistry(),
        indexer_configs={},
        source_priority=None,
        eval_kwargs={},
        validator_kwargs={},
        type_thresholds={"issue": "high"},
        failure_threshold=3,
    )

    async def _failing_search(
        *args: object,
        on_outcome=None,
        **kwargs: object,
    ) -> list[IssueSearchOutcome]:
        assert on_outcome is not None
        await on_outcome(_no_result_outcome(first))
        raise RuntimeError("provider failed")

    monkeypatch.setattr(search_task, "get_session_factory", lambda: db_factory)
    monkeypatch.setattr(
        search_task,
        "_build_task_search_runtime",
        AsyncMock(return_value=runtime),
    )
    monkeypatch.setattr(
        search_task,
        "load_wanted_issue_search_targets",
        AsyncMock(return_value=[first, second]),
    )
    monkeypatch.setattr(
        SearchService,
        "search_targets_quick_first",
        _failing_search,
    )

    with pytest.raises(RuntimeError, match="provider failed"):
        await search_task.search_wanted()

    async with db_factory() as session:
        logs = list(
            (await session.execute(select(SearchLog).order_by(SearchLog.issue_id))).scalars()
        )

    assert len(logs) == 2
    assert logs[0].details["run_state"] == "completed"
    assert logs[1].details["run_state"] == "failed"
    assert logs[1].details["action_status"] == "error"


@pytest.mark.asyncio
async def test_search_wanted_routes_matches_with_per_type_thresholds(
    db_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Automated routing must respect per-type thresholds, not a global confidence rule."""
    from pullbox.tasks import search_task

    issue_target = await _seed_issue(db_factory, issue_type=IssueType.ISSUE, comicvine_id=901)
    tpb_target = await _seed_issue(db_factory, issue_type=IssueType.TPB, comicvine_id=902)
    runtime = SearchRuntime(
        registry=ProviderRegistry(),
        indexer_configs={},
        source_priority=None,
        eval_kwargs={},
        validator_kwargs={},
        type_thresholds={"issue": "medium", "tpb": "high"},
        failure_threshold=3,
    )
    download_svc = AsyncMock()
    intervention_svc = AsyncMock()
    intervention_svc.has_pending_for_issue = AsyncMock(return_value=False)
    fake_logger = MagicMock()

    monkeypatch.setattr(search_task, "get_session_factory", lambda: db_factory)
    monkeypatch.setattr(
        search_task,
        "_build_task_search_runtime",
        AsyncMock(return_value=runtime),
    )
    monkeypatch.setattr(
        search_task,
        "load_wanted_issue_search_targets",
        AsyncMock(return_value=[issue_target, tpb_target]),
    )
    monkeypatch.setattr(
        SearchService,
        "search_targets_quick_first",
        AsyncMock(
            return_value=[
                _outcome(issue_target, confidence=MatchConfidence.MEDIUM),
                _outcome(tpb_target, confidence=MatchConfidence.MEDIUM),
            ]
        ),
    )
    monkeypatch.setattr(search_task, "_build_download_service", lambda registry: download_svc)
    monkeypatch.setattr(
        search_task,
        "InterventionService",
        lambda download_service: intervention_svc,
    )
    monkeypatch.setattr(search_task, "logger", fake_logger)

    await search_task.search_wanted()

    download_svc.send_to_client.assert_awaited_once()
    assert download_svc.send_to_client.await_args.args[2] == issue_target.issue_id
    intervention_svc.create_pending_match.assert_awaited_once()
    assert intervention_svc.create_pending_match.await_args.args[1] == tpb_target.issue_id
    complete_log = next(
        call for call in fake_logger.info.call_args_list if call.args[0] == "search_wanted_complete"
    )
    assert complete_log.kwargs["query_count"] == 2
    assert complete_log.kwargs["slow_indexer_count"] == 0


@pytest.mark.asyncio
async def test_search_wanted_records_no_result_attempts_and_advances_cursor(
    db_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scheduled sweeps should show attempted no-result searches in history."""
    from pullbox.tasks import search_task

    target = await _seed_issue(db_factory, issue_type=IssueType.ISSUE, comicvine_id=980)
    runtime = SearchRuntime(
        registry=ProviderRegistry(),
        indexer_configs={},
        source_priority=None,
        eval_kwargs={},
        validator_kwargs={},
        type_thresholds={"issue": "high"},
        failure_threshold=3,
    )
    no_result_outcome = IssueSearchOutcome(
        target=target,
        mode="fast",
        query_count=5,
        raw_results=[],
        filtered_results=[],
        matched=[],
        rejected=[],
        best_release=None,
        best_validation=None,
        search_details={"results_count": 0, "query_count": 5},
        elapsed_ms=10,
    )

    async with db_factory() as session:
        session.add(SystemConfig(key="search_wanted_cursor", value="[9, 99.0, 99]"))
        await session.commit()

    load_targets = AsyncMock(return_value=[target])
    search_targets_quick_first = AsyncMock(return_value=[no_result_outcome])

    monkeypatch.setattr(search_task, "get_session_factory", lambda: db_factory)
    monkeypatch.setattr(
        search_task,
        "_build_task_search_runtime",
        AsyncMock(return_value=runtime),
    )
    monkeypatch.setattr(search_task, "load_wanted_issue_search_targets", load_targets)
    monkeypatch.setattr(
        SearchService,
        "search_targets_quick_first",
        search_targets_quick_first,
    )

    await search_task.search_wanted()

    assert load_targets.await_count >= 1
    assert load_targets.await_args_list[0].kwargs == {"limit": 50, "after": (9, 99.0, 99)}

    async with db_factory() as session:
        cursor = await session.get(SystemConfig, "search_wanted_cursor")
        assert cursor is not None
        assert cursor.value == f"[{target.series_id}, {target.issue_number}, {target.issue_id}]"
        result = await session.execute(select(SearchLog))
        logs = list(result.scalars())

    assert len(logs) == 1
    assert logs[0].search_type == SearchType.AUTOMATED
    assert logs[0].results_found == 0
    assert logs[0].results_rejected == 0
    assert logs[0].best_confidence is None
    assert logs[0].details["run_state"] == "completed"
    assert logs[0].details["action_status"] == "no_results"
