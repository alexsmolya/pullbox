"""Focused coverage for the shared search-task orchestration paths."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from pullbox.models import Base
from pullbox.models.config import SystemConfig
from pullbox.models.indexer import IndexerConfig, IndexerType
from pullbox.models.issue import Issue, IssueStatus, IssueType
from pullbox.models.library import MatchConfidence
from pullbox.models.search_log import SearchLog, SearchType
from pullbox.models.series import Series, SeriesStatus, SeriesType
from pullbox.providers.base import ReleaseResult
from pullbox.services.search_service import IssueSearchOutcome, IssueSearchTarget
from pullbox.tasks import search_task

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


def _make_release(title: str = "Absolute Superman 009") -> ReleaseResult:
    return ReleaseResult(
        title=title,
        indexer_name="NZBgeek",
        download_url=f"https://example.com/{title.replace(' ', '_')}",
        size_bytes=100_000_000,
        age_days=2,
        seeders=None,
        leechers=None,
        grabs=50,
        is_torrent=False,
        category="7030",
        published_at=None,
    )


def _make_validation(release: ReleaseResult) -> SimpleNamespace:
    return SimpleNamespace(release=release, confidence=MatchConfidence.HIGH)


def _make_outcome(
    target: IssueSearchTarget,
    *,
    release: ReleaseResult | None,
    validation: SimpleNamespace | None,
    mode: str,
) -> IssueSearchOutcome:
    return IssueSearchOutcome(
        target=target,
        mode=mode,
        query_count=1,
        raw_results=[release] if release is not None else [],
        filtered_results=[release] if release is not None else [],
        matched=[validation] if validation is not None else [],
        rejected=[],
        best_release=release,
        best_validation=validation,
        search_details={"results_count": 1 if release is not None else 0},
        elapsed_ms=0,
        used_fallback=False,
    )


@pytest.fixture
async def task_db() -> AsyncGenerator[dict[str, object], None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_fk(dbapi_conn: object, _rec: object) -> None:
        dbapi_conn.execute("PRAGMA foreign_keys=ON")  # type: ignore[union-attr]

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        tpb_series = Series(
            comicvine_id=901,
            title="Search Task TPB",
            sort_title="search task tpb",
            year_start=2025,
            status=SeriesStatus.CONTINUING,
            series_type=SeriesType.STANDARD,
            monitored=True,
            issue_count=1,
        )
        wanted_series = Series(
            comicvine_id=902,
            title="Search Task Wanted",
            sort_title="search task wanted",
            year_start=2025,
            status=SeriesStatus.CONTINUING,
            series_type=SeriesType.STANDARD,
            monitored=True,
            issue_count=1,
        )
        session.add_all([tpb_series, wanted_series])
        await session.flush()

        tpb_issue = Issue(
            series_id=tpb_series.id,
            comicvine_id=1001,
            issue_number=1.0,
            title="Vol. 1: Deluxe",
            status=IssueStatus.WANTED,
            issue_type=IssueType.TPB,
        )
        wanted_issue = Issue(
            series_id=wanted_series.id,
            comicvine_id=1002,
            issue_number=9.0,
            title="Issue #9",
            status=IssueStatus.WANTED,
            issue_type=IssueType.ISSUE,
        )
        session.add_all([tpb_issue, wanted_issue])
        indexer = IndexerConfig(
            name="NZBgeek",
            indexer_type=IndexerType.NEWZNAB,
            url="https://example.test/newznab",
            api_key="encrypted-test-key",
            enabled=True,
            priority=25,
            failure_count=1,
        )
        session.add(indexer)
        session.add(SystemConfig(key="source_priority", value="not-json"))
        await session.commit()

        yield {
            "factory": factory,
            "tpb_series_id": tpb_series.id,
            "tpb_issue_id": tpb_issue.id,
            "wanted_issue_id": wanted_issue.id,
            "indexer_id": indexer.id,
        }

    await engine.dispose()


@pytest.mark.asyncio
async def test_build_task_search_runtime_handles_invalid_source_priority(
    task_db: dict[str, object],
) -> None:
    factory = task_db["factory"]

    with (
        patch(
            "pullbox.tasks.search_task.build_registry",
            new_callable=AsyncMock,
            return_value=(MagicMock(), {}),
        ),
    ):
        async with factory() as session:
            runtime = await search_task._build_task_search_runtime(session)

    assert runtime is not None
    assert runtime.source_priority is None


@pytest.mark.asyncio
async def test_build_mocked_wanted_outcome_preserves_best_validation(
    task_db: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = _make_release()
    validation = _make_validation(release)
    target = IssueSearchTarget(
        issue_id=task_db["wanted_issue_id"],
        series_id=22,
        series_title="Search Task Wanted",
        issue_number=9.0,
        issue_type=IssueType.ISSUE,
    )
    runtime = search_task.SearchRuntime(
        registry=MagicMock(),
        indexer_configs={},
        source_priority=None,
        eval_kwargs={},
        validator_kwargs={},
        type_thresholds=search_task.DEFAULT_TYPE_THRESHOLDS.copy(),
        failure_threshold=3,
    )
    search_svc = SimpleNamespace(evaluate_results=MagicMock(return_value=release))

    monkeypatch.setattr(
        search_task.BlocklistService,
        "filter_results",
        AsyncMock(return_value=[release]),
    )
    monkeypatch.setattr(
        search_task.ReleaseValidator,
        "validate_results",
        lambda self, results, **kwargs: [validation],
    )

    async with task_db["factory"]() as session:
        outcome = await search_task._build_mocked_wanted_outcome(
            session,
            search_svc,
            target,
            runtime,
            [release],
        )

    assert outcome.best_release is release
    assert outcome.best_validation is validation


@pytest.mark.asyncio
async def test_search_series_issues_real_path_uses_quick_first_batch_strategy(
    task_db: dict[str, object],
) -> None:
    factory = task_db["factory"]
    target = IssueSearchTarget(
        issue_id=task_db["tpb_issue_id"],
        series_id=task_db["tpb_series_id"],
        series_title="Search Task TPB",
        issue_number=1.0,
        issue_type=IssueType.TPB,
        issue_title="Vol. 1: Deluxe",
        series_year=2025,
    )
    release = _make_release("Search Task TPB Vol 1")
    validation = _make_validation(release)
    outcome = _make_outcome(target, release=release, validation=validation, mode="deep")
    outcome.search_details["search_strategy"] = "quick_first_deep_fallback"
    outcome.search_details["fast_search"] = {"query_count": 4, "results_count": 0}

    with (
        patch("pullbox.tasks.search_task.get_session_factory", return_value=factory),
        patch(
            "pullbox.tasks.search_task.build_registry",
            new_callable=AsyncMock,
            return_value=(MagicMock(), {}),
        ),
        patch(
            "pullbox.tasks.search_task.SearchService.search_targets_quick_first",
            new_callable=AsyncMock,
            return_value=[outcome],
        ) as search_targets_quick_first,
        patch("pullbox.tasks.search_task.DownloadService") as mock_download_cls,
        patch("pullbox.tasks.search_task.InterventionService") as mock_intervention_cls,
    ):
        mock_download_cls.return_value.send_to_client = AsyncMock(return_value=MagicMock())
        mock_intervention = mock_intervention_cls.return_value
        mock_intervention.has_pending_for_issue = AsyncMock(return_value=False)
        mock_intervention.create_pending_match = AsyncMock()

        result = await search_task.search_series_issues(task_db["tpb_series_id"])

    assert result == {"wanted": 1, "sent": 1, "queued": 0}
    assert search_targets_quick_first.await_count == 1
    assert search_targets_quick_first.await_args.kwargs["enable_deep_fallback"] is True
    assert search_targets_quick_first.await_args.kwargs["concurrency"] == 1
    mock_download_cls.return_value.send_to_client.assert_awaited_once()
    mock_intervention.create_pending_match.assert_not_awaited()


@pytest.mark.asyncio
async def test_search_series_issues_persists_indexer_health_before_download_routing(
    task_db: dict[str, object],
) -> None:
    factory = task_db["factory"]
    target = IssueSearchTarget(
        issue_id=task_db["tpb_issue_id"],
        series_id=task_db["tpb_series_id"],
        series_title="Search Task TPB",
        issue_number=1.0,
        issue_type=IssueType.TPB,
        issue_title="Vol. 1: Deluxe",
        series_year=2025,
    )
    release = _make_release("Search Task TPB Vol 1")
    validation = _make_validation(release)
    outcome = _make_outcome(target, release=release, validation=validation, mode="fast")
    loaded_indexer: IndexerConfig | None = None

    async def _build_registry(session, **_kwargs):
        nonlocal loaded_indexer
        loaded_indexer = await session.get(IndexerConfig, task_db["indexer_id"])
        assert loaded_indexer is not None
        return MagicMock(), {loaded_indexer.id: loaded_indexer}

    async def _search_targets(*_args, **_kwargs):
        assert loaded_indexer is not None
        loaded_indexer.failure_count = 0
        loaded_indexer.last_success_at = datetime.now(UTC)
        return [outcome]

    async def _send_to_client(*_args, **_kwargs):
        async with factory() as verification_session:
            persisted = await verification_session.get(IndexerConfig, task_db["indexer_id"])
            assert persisted is not None
            assert persisted.failure_count == 0
            assert persisted.last_success_at is not None
        return MagicMock()

    with (
        patch("pullbox.tasks.search_task.get_session_factory", return_value=factory),
        patch(
            "pullbox.tasks.search_task.build_registry",
            new_callable=AsyncMock,
            side_effect=_build_registry,
        ),
        patch(
            "pullbox.tasks.search_task.SearchService.search_targets_quick_first",
            new_callable=AsyncMock,
            side_effect=_search_targets,
        ),
        patch("pullbox.tasks.search_task.DownloadService") as mock_download_cls,
        patch("pullbox.tasks.search_task.InterventionService") as mock_intervention_cls,
    ):
        mock_download_cls.return_value.send_to_client = AsyncMock(side_effect=_send_to_client)
        mock_intervention = mock_intervention_cls.return_value
        mock_intervention.has_pending_for_issue = AsyncMock(return_value=False)
        mock_intervention.create_pending_match = AsyncMock()

        result = await search_task.search_series_issues(task_db["tpb_series_id"])

    assert result == {"wanted": 1, "sent": 1, "queued": 0}


@pytest.mark.asyncio
async def test_search_series_issues_updates_existing_pending_logs(
    task_db: dict[str, object],
) -> None:
    factory = task_db["factory"]
    target = IssueSearchTarget(
        issue_id=task_db["tpb_issue_id"],
        series_id=task_db["tpb_series_id"],
        series_title="Search Task TPB",
        issue_number=1.0,
        issue_type=IssueType.TPB,
        issue_title="Vol. 1: Deluxe",
        series_year=2025,
    )
    release = _make_release("Search Task TPB Vol 1")
    validation = _make_validation(release)
    outcome = _make_outcome(target, release=release, validation=validation, mode="deep")
    outcome.search_details["search_strategy"] = "quick_first_deep_fallback"
    outcome.search_details["fast_search"] = {"query_count": 4, "results_count": 0}

    async with factory() as session:
        pending_log = SearchLog(
            issue_id=task_db["tpb_issue_id"],
            series_title="Search Task TPB",
            issue_number=1.0,
            search_type=SearchType.BULK,
            results_found=0,
            results_grabbed=0,
            results_queued=0,
            results_rejected=0,
            details={"run_state": "running", "task_id": "search_series_1_123"},
        )
        session.add(pending_log)
        await session.commit()
        pending_log_id = pending_log.id

    with (
        patch("pullbox.tasks.search_task.get_session_factory", return_value=factory),
        patch(
            "pullbox.tasks.search_task.build_registry",
            new_callable=AsyncMock,
            return_value=(MagicMock(), {}),
        ),
        patch(
            "pullbox.tasks.search_task.SearchService.search_targets_quick_first",
            new_callable=AsyncMock,
            return_value=[outcome],
        ),
        patch("pullbox.tasks.search_task.DownloadService") as mock_download_cls,
        patch("pullbox.tasks.search_task.InterventionService") as mock_intervention_cls,
    ):
        mock_download_cls.return_value.send_to_client = AsyncMock(return_value=MagicMock())
        mock_intervention = mock_intervention_cls.return_value
        mock_intervention.has_pending_for_issue = AsyncMock(return_value=False)
        mock_intervention.create_pending_match = AsyncMock()

        result = await search_task.search_series_issues(
            task_db["tpb_series_id"],
            pending_log_ids_by_issue={task_db["tpb_issue_id"]: pending_log_id},
        )

    assert result == {"wanted": 1, "sent": 1, "queued": 0}

    async with factory() as session:
        result = await session.execute(select(SearchLog).order_by(SearchLog.id))
        logs = list(result.scalars().all())

    assert len(logs) == 1
    assert logs[0].id == pending_log_id
    assert logs[0].results_grabbed == 1
    assert logs[0].results_queued == 0
    assert logs[0].results_found == 1
    assert (logs[0].details or {}).get("run_state") == "completed"
    assert (logs[0].details or {}).get("search_strategy") == "quick_first_deep_fallback"
    assert (logs[0].details or {}).get("task_id") == "search_series_1_123"


@pytest.mark.asyncio
async def test_search_wanted_real_path_auto_grabs_best_match(
    task_db: dict[str, object],
) -> None:
    factory = task_db["factory"]
    target = IssueSearchTarget(
        issue_id=task_db["wanted_issue_id"],
        series_id=44,
        series_title="Search Task Wanted",
        issue_number=9.0,
        issue_type=IssueType.ISSUE,
        issue_title="Issue #9",
        series_year=2025,
    )
    release = _make_release("Search Task Wanted 009")
    validation = _make_validation(release)
    outcome = _make_outcome(target, release=release, validation=validation, mode="fast")

    with (
        patch("pullbox.tasks.search_task.get_session_factory", return_value=factory),
        patch(
            "pullbox.tasks.search_task.build_registry",
            new_callable=AsyncMock,
            return_value=(MagicMock(), {}),
        ),
        patch(
            "pullbox.tasks.search_task.SearchService.search_targets_quick_first",
            new_callable=AsyncMock,
            return_value=[outcome],
        ) as search_targets_quick_first,
        patch("pullbox.tasks.search_task.DownloadService") as mock_download_cls,
        patch("pullbox.tasks.search_task.InterventionService") as mock_intervention_cls,
    ):
        mock_download = mock_download_cls.return_value
        mock_download.send_to_client = AsyncMock(return_value=MagicMock())
        mock_intervention = mock_intervention_cls.return_value
        mock_intervention.has_pending_for_issue = AsyncMock(return_value=False)
        mock_intervention.create_pending_match = AsyncMock()

        await search_task.search_wanted()

    assert search_targets_quick_first.await_args.kwargs["enable_deep_fallback"] is True
    assert search_targets_quick_first.await_args.kwargs["concurrency"] == 1
    mock_download.send_to_client.assert_awaited_once()


@pytest.mark.asyncio
async def test_search_wanted_real_path_logs_issue_failures_without_bubbling(
    task_db: dict[str, object],
) -> None:
    factory = task_db["factory"]
    target = IssueSearchTarget(
        issue_id=task_db["wanted_issue_id"],
        series_id=44,
        series_title="Search Task Wanted",
        issue_number=9.0,
        issue_type=IssueType.ISSUE,
        issue_title="Issue #9",
        series_year=2025,
    )
    release = _make_release("Search Task Wanted 009")
    validation = _make_validation(release)
    outcome = _make_outcome(target, release=release, validation=validation, mode="fast")

    with (
        patch("pullbox.tasks.search_task.get_session_factory", return_value=factory),
        patch(
            "pullbox.tasks.search_task.build_registry",
            new_callable=AsyncMock,
            return_value=(MagicMock(), {}),
        ),
        patch(
            "pullbox.tasks.search_task.SearchService.search_targets_quick_first",
            new_callable=AsyncMock,
            return_value=[outcome],
        ),
        patch("pullbox.tasks.search_task.DownloadService") as mock_download_cls,
        patch("pullbox.tasks.search_task.InterventionService") as mock_intervention_cls,
    ):
        mock_download = mock_download_cls.return_value
        mock_download.send_to_client = AsyncMock(side_effect=RuntimeError("boom"))
        mock_intervention = mock_intervention_cls.return_value
        mock_intervention.has_pending_for_issue = AsyncMock(return_value=False)
        mock_intervention.create_pending_match = AsyncMock()

        await search_task.search_wanted()

    mock_download.send_to_client.assert_awaited_once()
