"""Background dispatch and restart recovery for direct acquisition."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from pullbox.models import Base
from pullbox.models.direct_acquisition import (
    DirectAcquisitionAttempt,
    DirectAcquisitionState,
    DirectArtifactAttempt,
    DirectArtifactFailureClass,
    DirectArtifactHostKind,
    DirectArtifactRouteKind,
    DirectArtifactState,
)
from pullbox.models.download import DownloadClientType, DownloadHistory, DownloadState
from pullbox.models.issue import Issue, IssueStatus, IssueType
from pullbox.models.series import Series, SeriesStatus, SeriesType
from pullbox.providers.artifact_hosts.contract import HostResolutionRequest
from pullbox.tasks.direct_acquisition_task import DirectAcquisitionRunner

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path


@pytest.fixture
async def session_factory(
    tmp_path: Path,
) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'direct-runner.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(
            Series(
                id=1,
                comicvine_id=900_001,
                title="Runner Series",
                sort_title="Runner Series",
                year_start=2026,
                status=SeriesStatus.CONTINUING,
                series_type=SeriesType.STANDARD,
                monitored=True,
                issue_count=1,
            )
        )
        session.add(
            Issue(
                id=1,
                series_id=1,
                comicvine_id=900_002,
                issue_number=1,
                issue_type=IssueType.ISSUE,
                status=IssueStatus.WANTED,
            )
        )
        attempt = DirectAcquisitionAttempt(
            id=1,
            request_key="direct-runner:1",
            issue_id=1,
            provider_identity="community.test",
            provider_candidate_id="candidate-1",
            state=DirectAcquisitionState.PLANNED,
            plan_revision=1,
            plan_snapshot={"schema_version": 1},
            progress_snapshot={"stage": "planned"},
            candidate_snapshot={"display_title": "Runner Series 001 (2026)"},
        )
        attempt.artifact_attempts = [
            DirectArtifactAttempt(
                id=1,
                sequence_no=0,
                artifact_identity="route:one",
                route_kind=DirectArtifactRouteKind.DIRECT,
                host_kind=DirectArtifactHostKind.GENERIC_HTTPS,
                state=DirectArtifactState.PLANNED,
                is_selected=True,
            )
        ]
        session.add(attempt)
        await session.commit()
    yield factory
    await engine.dispose()


def _source(name: str) -> HostResolutionRequest:
    return HostResolutionRequest(
        artifact_identity="route:one",
        host_kind=DirectArtifactHostKind.GENERIC_HTTPS,
        share_url=None,
        final_url=f"https://files.example/{name}.cbz?secret=hidden",
    )


@dataclass
class _Executor:
    started: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)
    sources: list[HostResolutionRequest] = field(default_factory=list)

    async def execute(self, session: AsyncSession, **kwargs: Any) -> None:
        self.sources.append(await kwargs["source_factory"]())
        self.sources.append(await kwargs["source_factory"]())
        self.started.set()
        await self.release.wait()
        attempt = await session.get(DirectAcquisitionAttempt, kwargs["acquisition_id"])
        assert attempt is not None
        attempt.state = DirectAcquisitionState.COMPLETED
        await session.commit()


@dataclass
class _CancellableExecutor:
    started: asyncio.Event = field(default_factory=asyncio.Event)
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)

    async def execute(self, _session: AsyncSession, **kwargs: Any) -> None:
        cancel_event = kwargs["cancel_event"]
        assert isinstance(cancel_event, asyncio.Event)
        self.started.set()
        await cancel_event.wait()
        self.cancelled.set()


@dataclass
class _InactiveCancelExecutor:
    calls: list[tuple[int, int]] = field(default_factory=list)

    async def execute(self, _session: AsyncSession, **_kwargs: Any) -> None:
        raise AssertionError("Inactive cancellation must not dispatch execution")

    async def cancel(self, _session: AsyncSession, **kwargs: Any) -> bool:
        self.calls.append((kwargs["acquisition_id"], kwargs["artifact_id"]))
        return True


@dataclass
class _FallbackExecutor:
    artifact_ids: list[int] = field(default_factory=list)

    async def execute(self, session: AsyncSession, **kwargs: Any) -> None:
        artifact_id = kwargs["artifact_id"]
        self.artifact_ids.append(artifact_id)
        attempt = await session.get(DirectAcquisitionAttempt, kwargs["acquisition_id"])
        artifact = await session.get(DirectArtifactAttempt, artifact_id)
        assert attempt is not None and artifact is not None
        if len(self.artifact_ids) == 1:
            artifact.state = DirectArtifactState.FAILED
            artifact.is_selected = False
            attempt.state = DirectAcquisitionState.QUEUED
            session.add(
                DirectArtifactAttempt(
                    id=2,
                    acquisition_attempt_id=attempt.id,
                    sequence_no=1,
                    artifact_identity="route:two",
                    route_kind=DirectArtifactRouteKind.DIRECT,
                    host_kind=DirectArtifactHostKind.PIXELDRAIN,
                    state=DirectArtifactState.PLANNED,
                    is_selected=True,
                )
            )
        else:
            attempt.state = DirectAcquisitionState.COMPLETED
            artifact.state = DirectArtifactState.COMPLETED
        await session.commit()


class _UnexpectedFailureExecutor:
    async def execute(self, _session: AsyncSession, **_kwargs: Any) -> None:
        raise RuntimeError("sensitive internal failure")


@pytest.mark.asyncio
async def test_runner_queues_once_uses_ephemeral_source_then_reresolves(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    executor = _Executor()
    resolver_calls = 0

    async def resolver(_session: AsyncSession, **_kwargs: Any) -> HostResolutionRequest:
        nonlocal resolver_calls
        resolver_calls += 1
        return _source("refreshed")

    runner = DirectAcquisitionRunner(
        session_factory,
        executor=executor,
        source_resolver=resolver,
    )

    assert await runner.dispatch(1, 1, initial_source=_source("initial")) is True
    assert await runner.dispatch(1, 1, initial_source=_source("duplicate")) is False
    await asyncio.wait_for(executor.started.wait(), timeout=1)
    assert executor.sources[0].final_url and "initial.cbz" in executor.sources[0].final_url
    assert executor.sources[1].final_url and "refreshed.cbz" in executor.sources[1].final_url
    assert resolver_calls == 1

    async with session_factory() as session:
        history = (await session.execute(select(DownloadHistory))).scalar_one()
        assert history.download_client is DownloadClientType.DIRECT
        assert history.external_id == "direct:1"
        assert history.download_url == "pullbox-direct://attempt/1"
        assert history.title == "Runner Series 001 (2026)"
        assert history.state is DownloadState.QUEUED
        assert "files.example" not in f"{history.download_url} {history.title}"

    executor.release.set()
    await runner.wait_idle()
    async with session_factory() as session:
        attempt = await session.get(DirectAcquisitionAttempt, 1)
        assert attempt is not None
        assert attempt.state is DirectAcquisitionState.COMPLETED
    await runner.aclose()


@pytest.mark.asyncio
async def test_runner_recovers_queued_attempt_without_ephemeral_urls(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        attempt = await session.get(DirectAcquisitionAttempt, 1)
        assert attempt is not None
        attempt.state = DirectAcquisitionState.QUEUED
        await session.commit()

    executor = _Executor()

    async def resolver(_session: AsyncSession, **_kwargs: Any) -> HostResolutionRequest:
        return _source("recovered")

    runner = DirectAcquisitionRunner(
        session_factory,
        executor=executor,
        source_resolver=resolver,
    )

    assert await runner.recover_and_dispatch(now=datetime(2026, 7, 28, tzinfo=UTC)) == 1
    await asyncio.wait_for(executor.started.wait(), timeout=1)
    assert all(
        source.final_url and "recovered.cbz" in source.final_url for source in executor.sources
    )
    executor.release.set()
    await runner.wait_idle()
    await runner.aclose()


@pytest.mark.asyncio
async def test_runner_continues_automatically_with_queued_fallback_route(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    executor = _FallbackExecutor()

    async def resolver(_session: AsyncSession, **kwargs: Any) -> HostResolutionRequest:
        return HostResolutionRequest(
            artifact_identity="route:two",
            host_kind=DirectArtifactHostKind.PIXELDRAIN,
            share_url="https://pixeldrain.com/u/fallback",
            final_url=None,
        )

    runner = DirectAcquisitionRunner(
        session_factory,
        executor=executor,
        source_resolver=resolver,
    )

    assert await runner.dispatch(1, 1, initial_source=_source("initial")) is True
    await runner.wait_idle()

    assert executor.artifact_ids == [1, 2]
    async with session_factory() as session:
        attempt = await session.get(DirectAcquisitionAttempt, 1)
        assert attempt is not None
        assert attempt.state is DirectAcquisitionState.COMPLETED
    await runner.aclose()


@pytest.mark.asyncio
async def test_runner_marks_unexpected_worker_failure_instead_of_leaving_download_stuck(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    runner = DirectAcquisitionRunner(
        session_factory,
        executor=_UnexpectedFailureExecutor(),
        source_resolver=lambda *_args, **_kwargs: _source("unused"),  # type: ignore[arg-type]
    )

    assert await runner.dispatch(1, 1, initial_source=_source("initial")) is True
    with pytest.raises(RuntimeError, match="sensitive internal failure"):
        await runner.wait_idle()

    async with session_factory() as session:
        attempt = await session.get(DirectAcquisitionAttempt, 1)
        artifact = await session.get(DirectArtifactAttempt, 1)
        assert attempt is not None and artifact is not None
        assert attempt.state is DirectAcquisitionState.FAILED
        assert artifact.state is DirectArtifactState.FAILED
        assert attempt.failure_class is DirectArtifactFailureClass.TRANSIENT_SOURCE
        assert attempt.failure_code == "direct_acquisition_worker_failed"
        assert attempt.error_message == "Direct acquisition stopped unexpectedly."
        assert "sensitive" not in repr(attempt.progress_snapshot)
    await runner.aclose()


@pytest.mark.asyncio
async def test_runner_cancel_signals_only_the_requested_acquisition(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    executor = _CancellableExecutor()

    async def resolver(_session: AsyncSession, **_kwargs: Any) -> HostResolutionRequest:
        return _source("cancelled")

    runner = DirectAcquisitionRunner(
        session_factory,
        executor=executor,
        source_resolver=resolver,
    )

    assert await runner.dispatch(1, 1) is True
    await asyncio.wait_for(executor.started.wait(), timeout=1)

    assert await runner.cancel(1) is True
    await asyncio.wait_for(executor.cancelled.wait(), timeout=1)
    await runner.wait_idle()
    assert await runner.cancel(999) is False
    await runner.aclose()


@pytest.mark.asyncio
async def test_runner_cancel_delegates_recoverable_inactive_attempt(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        attempt = await session.get(DirectAcquisitionAttempt, 1)
        artifact = await session.get(DirectArtifactAttempt, 1)
        assert attempt is not None and artifact is not None
        attempt.state = DirectAcquisitionState.RETRY_PENDING
        artifact.state = DirectArtifactState.RETRY_PENDING
        await session.commit()

    executor = _InactiveCancelExecutor()
    runner = DirectAcquisitionRunner(
        session_factory,
        executor=executor,
        source_resolver=lambda *_args, **_kwargs: _source("unused"),  # type: ignore[arg-type]
    )

    assert await runner.cancel(1) is True
    assert executor.calls == [(1, 1)]
    assert await runner.cancel(999) is False
    await runner.aclose()


@pytest.mark.asyncio
async def test_runner_reopens_terminal_attempt_for_explicit_retry(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        attempt = await session.get(DirectAcquisitionAttempt, 1)
        artifact = await session.get(DirectArtifactAttempt, 1)
        assert attempt is not None and artifact is not None
        attempt.state = DirectAcquisitionState.FAILED
        attempt.retry_count = attempt.max_retries
        attempt.completed_at = datetime(2026, 7, 28, tzinfo=UTC)
        artifact.state = DirectArtifactState.FAILED
        artifact.retry_count = artifact.max_retries
        artifact.completed_at = datetime(2026, 7, 28, tzinfo=UTC)
        await session.commit()

    executor = _Executor()

    async def resolver(_session: AsyncSession, **_kwargs: Any) -> HostResolutionRequest:
        return _source("manual-retry")

    runner = DirectAcquisitionRunner(
        session_factory,
        executor=executor,
        source_resolver=resolver,
    )

    assert await runner.retry(1) is True
    await asyncio.wait_for(executor.started.wait(), timeout=1)
    async with session_factory() as session:
        attempt = await session.get(DirectAcquisitionAttempt, 1)
        artifact = await session.get(DirectArtifactAttempt, 1)
        assert attempt is not None and artifact is not None
        assert attempt.state is DirectAcquisitionState.RETRY_PENDING
        assert artifact.state is DirectArtifactState.RETRY_PENDING
        assert attempt.retry_count == 0
        assert artifact.retry_count == 0
        assert attempt.completed_at is None
        assert artifact.completed_at is None
        assert attempt.progress_snapshot["stage"] == "retry_requested"

    executor.release.set()
    await runner.wait_idle()
    await runner.aclose()
