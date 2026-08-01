"""Routing tests shared by wanted and series search workflows."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from pullbox.models import Base
from pullbox.models.direct_acquisition import (
    DirectAcquisitionAttempt,
    DirectAcquisitionState,
    DirectArtifactFailureClass,
    DirectProviderConfig,
    DirectProviderState,
    DirectProviderTrustLevel,
)
from pullbox.models.issue import Issue, IssueStatus, IssueType
from pullbox.models.search_log import SearchLog, SearchType
from pullbox.models.series import Series, SeriesStatus, SeriesType
from pullbox.providers.base import ReleaseResult
from pullbox.providers.direct.contract import DirectCandidate, DirectParsedCandidate
from pullbox.services.direct_acquisition_planner_service import DirectAcquisitionPlanningError
from pullbox.services.direct_search_coordinator import (
    DirectSearchOutcome,
    DirectSearchProvider,
    DirectValidatedCandidate,
)
from pullbox.services.release_validator import ReleaseValidator
from pullbox.services.search_acquisition_router import route_search_acquisition
from pullbox.services.search_targets import IssueSearchOutcome, IssueSearchTarget

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


@pytest.fixture
async def db_factory() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _seed(
    factory: async_sessionmaker[AsyncSession],
) -> tuple[IssueSearchTarget, DirectSearchProvider, int]:
    async with factory() as session:
        series = Series(
            comicvine_id=7001,
            title="Batman",
            sort_title="batman",
            year_start=2016,
            status=SeriesStatus.CONTINUING,
            series_type=SeriesType.STANDARD,
            monitored=True,
        )
        session.add(series)
        await session.flush()
        issue = Issue(
            series_id=series.id,
            comicvine_id=8001,
            issue_number=1,
            issue_type=IssueType.ISSUE,
            status=IssueStatus.WANTED,
        )
        config = DirectProviderConfig(
            provider_id="pullbox.getcomics",
            display_name="GetComics",
            endpoint="http://provider:8780",
            enabled=True,
            priority=10,
            state=DirectProviderState.HEALTHY,
            trust_level=DirectProviderTrustLevel.VERIFIED_PULLBOX,
        )
        session.add_all([issue, config])
        await session.flush()
        log = SearchLog(
            issue_id=issue.id,
            series_title=series.title,
            issue_number=issue.issue_number,
            search_type=SearchType.AUTOMATED,
        )
        session.add(log)
        await session.commit()
        return (
            IssueSearchTarget(
                issue_id=issue.id,
                series_id=series.id,
                series_title=series.title,
                issue_number=issue.issue_number,
                issue_type=issue.issue_type,
                series_year=series.year_start,
            ),
            DirectSearchProvider(
                provider_config_id=config.id,
                provider_identity=config.provider_id,
                display_name=config.display_name,
                endpoint=config.endpoint,
                bearer_token="provider-token-with-enough-length",
            ),
            log.id,
        )


def _outcome(target: IssueSearchTarget, provider: DirectSearchProvider) -> IssueSearchOutcome:
    release = ReleaseResult(
        title="Batman 001 (2016) (Digital).cbz",
        indexer_name="GetComics",
        download_url="direct://candidate/opaque",
        size_bytes=None,
        age_days=None,
        seeders=None,
        leechers=None,
        grabs=None,
        is_torrent=False,
        category="Books/Comics",
        published_at=None,
    )
    validation = ReleaseValidator().validate_all_results(
        [release],
        wanted_series=target.series_title,
        wanted_issue=target.issue_number,
        wanted_year=target.series_year,
    )[0][0]
    result = DirectValidatedCandidate(
        provider=provider,
        candidate=DirectCandidate(
            provider_candidate_id="candidate-1",
            source_reference="https://getcomics.org/post",
            display_title=release.title,
            raw_title=release.title,
            parsed=DirectParsedCandidate(
                series_title=target.series_title,
                issue_numbers=["1"],
                year=target.series_year,
                format="cbz",
                quality="digital",
            ),
            provider_confidence=0.99,
        ),
        release=release,
        validation=validation,
    )
    return IssueSearchOutcome(
        target=target,
        mode="fast",
        query_count=1,
        raw_results=[],
        filtered_results=[],
        matched=[],
        rejected=[],
        best_release=None,
        best_validation=None,
        search_details={},
        elapsed_ms=1,
        direct_outcome=DirectSearchOutcome(
            matched=(result,),
            rejected=(),
            failures=(),
            providers_searched=1,
            elapsed_ms=1,
        ),
    )


def _outcome_with_indexer_fallback(
    target: IssueSearchTarget,
    provider: DirectSearchProvider,
) -> IssueSearchOutcome:
    outcome = _outcome(target, provider)
    release = ReleaseResult(
        title="Batman 001 (2016) (Digital).cbz",
        indexer_name="Fallback Indexer",
        download_url="https://indexer.example/download/1",
        size_bytes=None,
        age_days=None,
        seeders=None,
        leechers=None,
        grabs=None,
        is_torrent=False,
        category="Books/Comics",
        published_at=None,
    )
    validation = ReleaseValidator().validate_all_results(
        [release],
        wanted_series=target.series_title,
        wanted_issue=target.issue_number,
        wanted_year=target.series_year,
    )[0][0]
    return replace(
        outcome,
        raw_results=[release],
        filtered_results=[release],
        matched=[validation],
        best_release=release,
        best_validation=validation,
    )


async def test_direct_result_below_threshold_becomes_durable_intervention(
    db_factory: async_sessionmaker[AsyncSession],
) -> None:
    target, provider, search_log_id = await _seed(db_factory)
    download_service = AsyncMock()
    intervention_service = AsyncMock()
    runner = SimpleNamespace(dispatch=AsyncMock())

    async with db_factory() as session:
        routed = await route_search_acquisition(
            session,
            outcome=_outcome(target, provider),
            search_log_id=search_log_id,
            eval_kwargs={},
            type_thresholds={"issue": "never"},
            download_service=download_service,
            intervention_service=intervention_service,
            runner=runner,
        )
        await session.commit()

    assert routed.grabbed == 0
    assert routed.queued == 1
    assert routed.action_status == "intervention"
    assert routed.source_kind == "direct"
    download_service.send_to_client.assert_not_awaited()
    intervention_service.create_pending_match.assert_not_awaited()
    intervention_service.create_direct_pending_match.assert_awaited_once()
    direct_args = intervention_service.create_direct_pending_match.await_args.args
    assert direct_args[1:3] == (target.issue_id, 1)
    runner.dispatch.assert_not_awaited()
    async with db_factory() as session:
        attempt = await session.get(DirectAcquisitionAttempt, 1)
    assert attempt is not None
    assert attempt.state is DirectAcquisitionState.INTERVENTION
    assert attempt.failure_class is DirectArtifactFailureClass.USER_ACTION
    assert attempt.failure_code == "semantic_review_required"
    assert attempt.progress_snapshot["stage"] == "intervention"


@pytest.mark.asyncio
async def test_direct_planning_failure_creates_visible_intervention(
    db_factory: async_sessionmaker[AsyncSession],
) -> None:
    target, provider, search_log_id = await _seed(db_factory)
    intervention_service = AsyncMock()
    planner = AsyncMock(
        side_effect=DirectAcquisitionPlanningError(
            "artifact_host_auth_required",
            "An enabled account is required.",
        )
    )

    async with db_factory() as session:
        routed = await route_search_acquisition(
            session,
            outcome=_outcome(target, provider),
            search_log_id=search_log_id,
            eval_kwargs={},
            type_thresholds={"issue": "high"},
            download_service=AsyncMock(),
            intervention_service=intervention_service,
            runner=SimpleNamespace(dispatch=AsyncMock()),
            source_priority=["direct", "torrent", "usenet"],
            planner=planner,
        )

    assert routed.action_status == "intervention"
    intervention_service.create_direct_pending_match.assert_awaited_once()


@pytest.mark.asyncio
async def test_non_intervention_direct_failure_falls_back_to_ranked_indexer(
    db_factory: async_sessionmaker[AsyncSession],
) -> None:
    target, provider, search_log_id = await _seed(db_factory)
    download_service = AsyncMock()
    intervention_service = AsyncMock()
    planner = AsyncMock(
        side_effect=DirectAcquisitionPlanningError(
            "source_quota_limited",
            "Source quota is exhausted.",
            failure_class=DirectArtifactFailureClass.PROVIDER_UNAVAILABLE,
            intervention=False,
        )
    )

    async with db_factory() as session:
        routed = await route_search_acquisition(
            session,
            outcome=_outcome_with_indexer_fallback(target, provider),
            search_log_id=search_log_id,
            eval_kwargs={},
            type_thresholds={"issue": "high"},
            download_service=download_service,
            intervention_service=intervention_service,
            runner=SimpleNamespace(dispatch=AsyncMock()),
            source_priority=["direct", "torrent", "usenet"],
            planner=planner,
        )

    assert routed.action_status == "downloading"
    assert routed.source_kind == "indexer"
    assert routed.notices == ("GetComics quota exhausted; continuing with other sources.",)
    download_service.send_to_client.assert_awaited_once()
    intervention_service.create_direct_pending_match.assert_not_awaited()


@pytest.mark.asyncio
async def test_automatic_quota_reserve_skips_direct_and_preserves_manual_slots(
    db_factory: async_sessionmaker[AsyncSession],
) -> None:
    target, provider, search_log_id = await _seed(db_factory)
    download_service = AsyncMock()
    planner = AsyncMock()
    async with db_factory() as session:
        config = await session.get(DirectProviderConfig, provider.provider_config_id)
        assert config is not None
        config.manifest_snapshot = {"capabilities": {"quota": True}}
        config.configuration_metadata = {
            "automatic_quota_reserve": 5,
            "quota_status": {
                "remaining": 5,
                "limit": 25,
                "window_seconds": 64_800,
                "reset_at": None,
                "observed_at": "2026-07-31T12:00:00+00:00",
            },
        }
        await session.commit()

        routed = await route_search_acquisition(
            session,
            outcome=_outcome_with_indexer_fallback(target, provider),
            search_log_id=search_log_id,
            eval_kwargs={},
            type_thresholds={"issue": "high"},
            download_service=download_service,
            intervention_service=AsyncMock(),
            runner=SimpleNamespace(dispatch=AsyncMock()),
            source_priority=["direct", "torrent", "usenet"],
            planner=planner,
        )

    assert routed.source_kind == "indexer"
    assert routed.notices == (
        "GetComics automatic reserve reached; reserved slots remain available for manual grabs.",
    )
    planner.assert_not_awaited()
    download_service.send_to_client.assert_awaited_once()


@pytest.mark.asyncio
async def test_non_intervention_direct_failure_without_fallback_does_not_queue_review(
    db_factory: async_sessionmaker[AsyncSession],
) -> None:
    target, provider, search_log_id = await _seed(db_factory)
    intervention_service = AsyncMock()
    planner = AsyncMock(
        side_effect=DirectAcquisitionPlanningError(
            "source_authentication_required",
            "Source authentication is required.",
            failure_class=DirectArtifactFailureClass.PROVIDER_UNAVAILABLE,
            intervention=False,
        )
    )

    async with db_factory() as session:
        routed = await route_search_acquisition(
            session,
            outcome=_outcome(target, provider),
            search_log_id=search_log_id,
            eval_kwargs={},
            type_thresholds={"issue": "high"},
            download_service=AsyncMock(),
            intervention_service=intervention_service,
            runner=SimpleNamespace(dispatch=AsyncMock()),
            planner=planner,
        )

    assert routed.grabbed == 0
    assert routed.queued == 0
    assert routed.action_status == "source_unavailable"
    intervention_service.create_direct_pending_match.assert_not_awaited()
