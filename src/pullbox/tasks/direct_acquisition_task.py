"""Restart-safe background dispatch for direct acquisition attempts."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

import structlog
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from pullbox.models.direct_acquisition import (
    DirectAcquisitionAttempt,
    DirectAcquisitionState,
    DirectArtifactAttempt,
    DirectArtifactFailureClass,
    DirectArtifactState,
)
from pullbox.providers.artifact_hosts.contract import HostResolutionRequest
from pullbox.services.direct_acquisition_planner_service import (
    resolve_planned_artifact_source,
)
from pullbox.services.direct_acquisition_recovery import load_recoverable_acquisitions
from pullbox.services.direct_acquisition_state import (
    advance_acquisition_progress,
    reopen_terminal_acquisition_for_retry,
    transition_acquisition,
    transition_artifact,
)
from pullbox.services.direct_download_history_adapter import (
    ensure_direct_download_history,
    sync_direct_download_history,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = structlog.get_logger(__name__)


class DirectExecutor(Protocol):
    async def execute(
        self,
        session: AsyncSession,
        *,
        acquisition_id: int,
        artifact_id: int,
        source_factory: Callable[[], Awaitable[HostResolutionRequest]],
        cancel_event: asyncio.Event | None = None,
    ) -> object: ...

    async def cancel(
        self,
        session: AsyncSession,
        *,
        acquisition_id: int,
        artifact_id: int,
    ) -> bool: ...


SourceResolver = Callable[..., Awaitable[HostResolutionRequest]]


@dataclass(frozen=True, slots=True)
class _ActiveRun:
    task: asyncio.Task[None]
    cancel_event: asyncio.Event


class DirectAcquisitionRunner:
    """Dispatch durable attempts once and reconstruct ephemeral URLs on recovery."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        executor: DirectExecutor,
        source_resolver: SourceResolver = resolve_planned_artifact_source,
    ) -> None:
        self._session_factory = session_factory
        self._executor = executor
        self._source_resolver = source_resolver
        self._active: dict[tuple[int, int], _ActiveRun] = {}
        self._lock = asyncio.Lock()

    async def dispatch(
        self,
        acquisition_id: int,
        artifact_id: int,
        *,
        initial_source: HostResolutionRequest | None = None,
    ) -> bool:
        """Queue one attempt, returning false when the same artifact is already active."""
        key = (acquisition_id, artifact_id)
        async with self._lock:
            current = self._active.get(key)
            if current is not None and not current.task.done():
                return False
            await self._mark_queued(acquisition_id, artifact_id)
            cancel_event = asyncio.Event()
            task = asyncio.create_task(
                self._run(
                    acquisition_id,
                    artifact_id,
                    initial_source=initial_source,
                    cancel_event=cancel_event,
                ),
                name=f"direct-acquisition-{acquisition_id}-{artifact_id}",
            )
            self._active[key] = _ActiveRun(task=task, cancel_event=cancel_event)

            def finish(completed: asyncio.Task[None]) -> None:
                self._finish(key, completed)

            task.add_done_callback(finish)
            return True

    async def cancel(self, acquisition_id: int) -> bool:
        """Signal cooperative cancellation for an active direct acquisition."""
        async with self._lock:
            active = [
                run
                for key, run in self._active.items()
                if key[0] == acquisition_id and not run.task.done()
            ]
            for run in active:
                run.cancel_event.set()
        if not active:
            async with self._session_factory() as session:
                attempt = (
                    await session.execute(
                        select(DirectAcquisitionAttempt)
                        .options(selectinload(DirectAcquisitionAttempt.artifact_attempts))
                        .where(DirectAcquisitionAttempt.id == acquisition_id)
                    )
                ).scalar_one_or_none()
                if attempt is None:
                    return False
                selected = [
                    artifact for artifact in attempt.artifact_attempts if artifact.is_selected
                ]
                if len(selected) != 1:
                    return False
                return await self._executor.cancel(
                    session,
                    acquisition_id=attempt.id,
                    artifact_id=selected[0].id,
                )
        await asyncio.gather(*(run.task for run in active), return_exceptions=True)
        return True

    async def retry(self, acquisition_id: int) -> bool:
        """Resume an intervention or explicitly reopen one terminal direct attempt."""
        async with self._lock:
            if any(
                key[0] == acquisition_id and not run.task.done()
                for key, run in self._active.items()
            ):
                return False

        async with self._session_factory() as session:
            attempt = (
                await session.execute(
                    select(DirectAcquisitionAttempt)
                    .options(selectinload(DirectAcquisitionAttempt.artifact_attempts))
                    .where(DirectAcquisitionAttempt.id == acquisition_id)
                )
            ).scalar_one_or_none()
            if attempt is None:
                return False
            selected = [artifact for artifact in attempt.artifact_attempts if artifact.is_selected]
            if len(selected) != 1:
                return False
            artifact = selected[0]
            if attempt.state in {
                DirectAcquisitionState.FAILED,
                DirectAcquisitionState.CANCELLED,
            }:
                reopen_terminal_acquisition_for_retry(attempt, artifact)
                await sync_direct_download_history(
                    session,
                    attempt,
                    artifact,
                    at=datetime.now(UTC),
                )
                await session.commit()
            elif attempt.state is DirectAcquisitionState.INTERVENTION:
                advance_acquisition_progress(
                    attempt,
                    revision=attempt.progress_revision + 1,
                    snapshot={
                        "schema_version": 1,
                        "stage": "retry_requested",
                        "artifact_attempt_id": artifact.id,
                    },
                )
                await session.commit()
            else:
                return False
            artifact_id = artifact.id

        return await self.dispatch(acquisition_id, artifact_id)

    async def recover_and_dispatch(
        self,
        *,
        now: datetime | None = None,
        limit: int = 100,
    ) -> int:
        """Resume runnable persisted attempts without any previously signed URLs."""
        async with self._session_factory() as session:
            attempts = await load_recoverable_acquisitions(
                session,
                now=now or datetime.now(UTC),
                limit=limit,
            )
            recoverable = [
                (attempt.id, artifact.id)
                for attempt in attempts
                for artifact in attempt.artifact_attempts
                if artifact.is_selected
            ]
        recovered = 0
        for acquisition_id, artifact_id in recoverable:
            if await self.dispatch(acquisition_id, artifact_id):
                recovered += 1
        return recovered

    async def wait_idle(self) -> None:
        """Wait until all currently dispatched attempts reach a checkpoint."""
        while True:
            tasks = tuple(run.task for run in self._active.values() if not run.task.done())
            if not tasks:
                return
            await asyncio.gather(*tasks)

    async def aclose(self) -> None:
        """Cancel active workers, preserving executor restart checkpoints."""
        tasks = tuple(run.task for run in self._active.values() if not run.task.done())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        close = getattr(self._executor, "aclose", None)
        if callable(close):
            await close()

    async def _mark_queued(self, acquisition_id: int, artifact_id: int) -> None:
        async with self._session_factory() as session:
            attempt = await session.get(DirectAcquisitionAttempt, acquisition_id)
            artifact = await session.get(DirectArtifactAttempt, artifact_id)
            if attempt is None or artifact is None or artifact.acquisition_attempt_id != attempt.id:
                raise ValueError("Direct acquisition attempt or artifact was not found.")
            await ensure_direct_download_history(
                session,
                attempt,
                artifact,
                at=datetime.now(UTC),
            )
            if attempt.state is DirectAcquisitionState.PLANNED:
                transition_acquisition(attempt, DirectAcquisitionState.QUEUED)
                await session.commit()

    async def _run(
        self,
        acquisition_id: int,
        artifact_id: int,
        *,
        initial_source: HostResolutionRequest | None,
        cancel_event: asyncio.Event,
    ) -> None:
        first_source = initial_source
        current_artifact_id = artifact_id

        async with self._session_factory() as session:
            while True:
                artifact_id_for_source = current_artifact_id

                async def source_factory(
                    artifact_id: int = artifact_id_for_source,
                ) -> HostResolutionRequest:
                    nonlocal first_source
                    if first_source is not None:
                        source = first_source
                        first_source = None
                        return source
                    return await self._source_resolver(
                        session,
                        acquisition_id=acquisition_id,
                        artifact_id=artifact_id,
                    )

                try:
                    await self._executor.execute(
                        session,
                        acquisition_id=acquisition_id,
                        artifact_id=current_artifact_id,
                        source_factory=source_factory,
                        cancel_event=cancel_event,
                    )
                except Exception:
                    await session.rollback()
                    await self._mark_unexpected_failure(
                        session,
                        acquisition_id=acquisition_id,
                        artifact_id=current_artifact_id,
                    )
                    raise
                attempt = (
                    await session.execute(
                        select(DirectAcquisitionAttempt)
                        .options(selectinload(DirectAcquisitionAttempt.artifact_attempts))
                        .where(DirectAcquisitionAttempt.id == acquisition_id)
                        .execution_options(populate_existing=True)
                    )
                ).scalar_one()
                if attempt.state is not DirectAcquisitionState.QUEUED:
                    return
                selected = [
                    artifact for artifact in attempt.artifact_attempts if artifact.is_selected
                ]
                if len(selected) != 1 or selected[0].id == current_artifact_id:
                    raise RuntimeError("Queued direct fallback has no new selected artifact.")
                current_artifact_id = selected[0].id

    async def _mark_unexpected_failure(
        self,
        session: AsyncSession,
        *,
        acquisition_id: int,
        artifact_id: int,
    ) -> None:
        attempt = await session.get(DirectAcquisitionAttempt, acquisition_id)
        artifact = await session.get(DirectArtifactAttempt, artifact_id)
        if attempt is None or artifact is None:
            return
        if attempt.state in {
            DirectAcquisitionState.COMPLETED,
            DirectAcquisitionState.CANCELLED,
            DirectAcquisitionState.FAILED,
        }:
            return
        attempt.failure_class = DirectArtifactFailureClass.TRANSIENT_SOURCE
        attempt.failure_code = "direct_acquisition_worker_failed"
        attempt.error_message = "Direct acquisition stopped unexpectedly."
        artifact.failure_class = DirectArtifactFailureClass.TRANSIENT_SOURCE
        artifact.failure_code = "direct_acquisition_worker_failed"
        artifact.error_message = "Direct acquisition stopped unexpectedly."
        transition_artifact(artifact, DirectArtifactState.FAILED)
        transition_acquisition(attempt, DirectAcquisitionState.FAILED)
        advance_acquisition_progress(
            attempt,
            revision=attempt.progress_revision + 1,
            snapshot={
                "schema_version": 1,
                "stage": "failed",
                "artifact_attempt_id": artifact.id,
                "failure_code": "direct_acquisition_worker_failed",
            },
        )
        await sync_direct_download_history(
            session,
            attempt,
            artifact,
            at=datetime.now(UTC),
        )
        await session.commit()

    def _finish(self, key: tuple[int, int], task: asyncio.Task[None]) -> None:
        self._active.pop(key, None)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.error(
                "direct_acquisition_worker_failed",
                acquisition_id=key[0],
                artifact_id=key[1],
                error_type=type(error).__name__,
            )


_runner: DirectAcquisitionRunner | None = None


def set_direct_acquisition_runner(runner: DirectAcquisitionRunner | None) -> None:
    """Set the process-local runner used by API and startup dispatch."""
    global _runner
    _runner = runner


def get_direct_acquisition_runner() -> DirectAcquisitionRunner:
    """Return the initialized direct runner."""
    if _runner is None:
        raise RuntimeError("Direct acquisition runner is not initialized.")
    return _runner
