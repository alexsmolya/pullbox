"""Route one unified search winner to its native acquisition adapter."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

from pullbox.models.direct_acquisition import (
    DirectAcquisitionAttempt,
    DirectAcquisitionState,
    DirectArtifactFailureClass,
)
from pullbox.services.direct_acquisition_planner_service import (
    DirectAcquisitionPlanningError,
    DirectAcquisitionPlanningResult,
    plan_direct_acquisition,
)
from pullbox.services.direct_acquisition_state import (
    advance_acquisition_progress,
    transition_acquisition,
)
from pullbox.services.direct_search_coordinator import persist_direct_search_discoveries
from pullbox.services.search_runtime import should_auto_grab
from pullbox.services.search_source_selection import select_search_source

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from pullbox.providers.artifact_hosts.contract import HostResolutionRequest
    from pullbox.providers.base import ReleaseResult
    from pullbox.services.direct_search_coordinator import (
        DirectSearchDiscovery,
        DirectValidatedCandidate,
    )
    from pullbox.services.release_validator import ValidationResult
    from pullbox.services.search_targets import IssueSearchOutcome
    from pullbox.services.search_types import SearchEvalKwargs


class DownloadServiceLike(Protocol):
    async def send_to_client(
        self,
        session: AsyncSession,
        release: ReleaseResult,
        issue_id: int,
    ) -> object: ...


class InterventionServiceLike(Protocol):
    async def has_pending_for_issue(self, session: AsyncSession, issue_id: int) -> bool: ...

    async def create_pending_match(
        self,
        session: AsyncSession,
        issue_id: int,
        release: ReleaseResult,
        validation: ValidationResult,
    ) -> object: ...

    async def create_direct_pending_match(
        self,
        session: AsyncSession,
        issue_id: int,
        attempt_id: int,
        result: DirectValidatedCandidate,
    ) -> object: ...


class DirectRunnerLike(Protocol):
    async def dispatch(
        self,
        acquisition_id: int,
        artifact_id: int,
        *,
        initial_source: HostResolutionRequest | None = None,
    ) -> bool: ...


DirectPlanner = Callable[..., Awaitable[DirectAcquisitionPlanningResult]]


@dataclass(frozen=True, slots=True)
class SearchAcquisitionRoutingResult:
    """Compact outcome consumed by search history and task accounting."""

    grabbed: int
    queued: int
    action_status: str
    best_confidence: str | None
    source_kind: Literal["indexer", "direct"] | None


async def route_search_acquisition(
    session: AsyncSession,
    *,
    outcome: IssueSearchOutcome,
    search_log_id: int,
    eval_kwargs: SearchEvalKwargs,
    type_thresholds: dict[str, str],
    download_service: DownloadServiceLike,
    intervention_service: InterventionServiceLike,
    runner: DirectRunnerLike | None,
    planner: DirectPlanner = plan_direct_acquisition,
) -> SearchAcquisitionRoutingResult:
    """Persist all discoveries and route the best result through its own adapter."""
    target = outcome.target
    discoveries: tuple[DirectSearchDiscovery, ...] = ()
    if outcome.direct_outcome is not None:
        discoveries = await persist_direct_search_discoveries(
            session,
            target,
            outcome.direct_outcome,
            search_log_id=search_log_id,
        )

    selected = select_search_source(outcome, eval_kwargs)
    if selected is None:
        return SearchAcquisitionRoutingResult(0, 0, "no_match", None, None)

    confidence = selected.validation.confidence.value
    auto_grab = should_auto_grab(
        selected.validation.confidence,
        target.issue_type,
        type_thresholds,
    )
    if selected.source_kind == "indexer":
        if auto_grab:
            await download_service.send_to_client(
                session,
                selected.release,
                target.issue_id,
            )
            return SearchAcquisitionRoutingResult(
                1,
                0,
                "downloading",
                confidence,
                "indexer",
            )
        if not await intervention_service.has_pending_for_issue(session, target.issue_id):
            await intervention_service.create_pending_match(
                session,
                target.issue_id,
                selected.release,
                selected.validation,
            )
            return SearchAcquisitionRoutingResult(0, 1, "queued", confidence, "indexer")
        return SearchAcquisitionRoutingResult(
            0,
            0,
            "pending_exists",
            confidence,
            "indexer",
        )

    discovery = next(item for item in discoveries if item.result is selected.direct_result)
    if not auto_grab:
        attempt = await session.get(DirectAcquisitionAttempt, discovery.attempt_id)
        if attempt is None:
            raise RuntimeError("Persisted direct acquisition attempt was not found.")
        transition_acquisition(attempt, DirectAcquisitionState.INTERVENTION)
        attempt.failure_class = DirectArtifactFailureClass.USER_ACTION
        attempt.failure_code = "semantic_review_required"
        attempt.error_message = "Review this direct result before downloading."
        advance_acquisition_progress(
            attempt,
            revision=attempt.progress_revision + 1,
            snapshot={
                "schema_version": 1,
                "stage": "intervention",
                "failure_code": "semantic_review_required",
            },
        )
        if selected.direct_result is None:
            raise RuntimeError("Selected direct result is unavailable.")
        await intervention_service.create_direct_pending_match(
            session,
            target.issue_id,
            discovery.attempt_id,
            selected.direct_result,
        )
        return SearchAcquisitionRoutingResult(
            0,
            1,
            "intervention",
            confidence,
            "direct",
        )

    # Make provenance restart-safe before provider resolution performs network I/O.
    await session.commit()
    try:
        planned = await planner(session, acquisition_id=discovery.attempt_id)
    except DirectAcquisitionPlanningError:
        if selected.direct_result is None:
            raise RuntimeError("Selected direct result is unavailable.") from None
        await intervention_service.create_direct_pending_match(
            session,
            target.issue_id,
            discovery.attempt_id,
            selected.direct_result,
        )
        await session.commit()
        return SearchAcquisitionRoutingResult(
            0,
            1,
            "intervention",
            confidence,
            "direct",
        )
    await session.commit()
    if runner is None:
        raise RuntimeError("Direct acquisition runner is not initialized.")
    await runner.dispatch(
        planned.attempt.id,
        planned.selected_artifact.id,
        initial_source=planned.initial_source,
    )
    return SearchAcquisitionRoutingResult(
        1,
        0,
        "downloading",
        confidence,
        "direct",
    )
