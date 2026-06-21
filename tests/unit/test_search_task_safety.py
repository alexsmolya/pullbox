"""Automated search safety contracts."""

from __future__ import annotations

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


@pytest.mark.asyncio
async def test_search_wanted_uses_bounded_fast_search_not_deep_manual_fanout(
    db_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wanted sweeps should use the bounded shared quick-first batch strategy."""
    from pullbox.tasks import search_task

    target = IssueSearchTarget(
        issue_id=1,
        series_id=10,
        series_title="Absolute Flash",
        issue_number=1.0,
        issue_type=IssueType.ISSUE,
        issue_title="Issue #1",
        series_year=2025,
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
