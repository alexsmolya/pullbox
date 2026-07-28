"""Pure coverage and route planning for direct-download candidates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pullbox.core.exceptions import ValidationError
from pullbox.models.direct_acquisition import DirectHostAccountState

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pullbox.models.direct_acquisition import (
        DirectArtifactHostKind,
        DirectArtifactRouteKind,
    )

_MAX_PLANNER_STATES = 100_000
_SelectionKey = tuple[int, int, int, int, int, int, int, float, int, tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class DirectRouteOption:
    """One safe transfer route offered for a provider artifact."""

    route_identity: str
    route_kind: DirectArtifactRouteKind
    host_kind: DirectArtifactHostKind
    transport_rank: int
    eligible: bool
    eligibility_code: str
    host_preference: int
    account_state: DirectHostAccountState
    quota_remaining: int | None
    resumable: bool
    resolver_required: bool


@dataclass(frozen=True, slots=True)
class DirectArtifactOption:
    """Content evidence and routes for one normalized provider artifact."""

    provider_identity: str
    provider_candidate_id: str
    artifact_identity: str
    coverage: frozenset[str]
    semantic_rank: int
    quality_rank: int
    expected_size: int | None
    provider_confidence: float
    provider_priority: int
    routes: tuple[DirectRouteOption, ...]


@dataclass(frozen=True, slots=True)
class PlannedDirectArtifact:
    """An artifact selected for coverage with stable route ordering."""

    provider_identity: str
    provider_candidate_id: str
    artifact_identity: str
    coverage: frozenset[str]
    expected_size: int | None
    ordered_routes: tuple[DirectRouteOption, ...]
    selected_route_identity: str


@dataclass(frozen=True, slots=True)
class DirectCoveragePlan:
    """Deterministic planner result suitable for durable snapshot creation."""

    requested: frozenset[str]
    selected: tuple[PlannedDirectArtifact, ...]
    uncovered: frozenset[str]
    complete: bool
    explanation_code: str
    pinned_route_applied: bool


def plan_direct_coverage(
    requested: frozenset[str],
    artifacts: Sequence[DirectArtifactOption],
    *,
    pinned_route_identity: str | None = None,
) -> DirectCoveragePlan:
    """Choose deterministic content first, then rank safe transfer routes."""
    _validate_inputs(requested, artifacts)
    if not requested:
        return DirectCoveragePlan(
            requested=requested,
            selected=(),
            uncovered=frozenset(),
            complete=True,
            explanation_code="nothing_requested",
            pinned_route_applied=False,
        )

    eligible = tuple(
        sorted(
            (
                artifact
                for artifact in artifacts
                if artifact.coverage & requested
                and any(route.eligible for route in artifact.routes)
            ),
            key=_artifact_order_key,
        )
    )
    selected_options = _select_artifacts(requested, eligible)
    covered = frozenset().union(*(item.coverage & requested for item in selected_options))
    uncovered = requested - covered

    planned: list[PlannedDirectArtifact] = []
    pin_applied = False
    pin_rejected = False
    for artifact in selected_options:
        ordered_routes = tuple(sorted(artifact.routes, key=_route_order_key))
        safe_routes = tuple(route for route in ordered_routes if route.eligible)
        selected_route = safe_routes[0]
        if pinned_route_identity is not None:
            pinned = next(
                (
                    route
                    for route in ordered_routes
                    if route.route_identity == pinned_route_identity
                ),
                None,
            )
            if pinned is not None and pinned.eligible:
                selected_route = pinned
                pin_applied = True
            elif pinned is not None:
                pin_rejected = True
        planned.append(
            PlannedDirectArtifact(
                provider_identity=artifact.provider_identity,
                provider_candidate_id=artifact.provider_candidate_id,
                artifact_identity=artifact.artifact_identity,
                coverage=artifact.coverage,
                expected_size=artifact.expected_size,
                ordered_routes=ordered_routes,
                selected_route_identity=selected_route.route_identity,
            )
        )

    if pin_rejected:
        explanation = "pinned_route_ineligible"
    elif uncovered:
        explanation = "incomplete_coverage"
    else:
        explanation = "complete_coverage"
    return DirectCoveragePlan(
        requested=requested,
        selected=tuple(planned),
        uncovered=uncovered,
        complete=not uncovered,
        explanation_code=explanation,
        pinned_route_applied=pin_applied,
    )


def _select_artifacts(
    requested: frozenset[str],
    artifacts: tuple[DirectArtifactOption, ...],
) -> tuple[DirectArtifactOption, ...]:
    """Keep the best exact plan for each reachable coverage state."""
    if not artifacts:
        return ()
    issue_positions = {issue: index for index, issue in enumerate(sorted(requested))}
    full_mask = (1 << len(issue_positions)) - 1
    masks = tuple(
        sum(1 << issue_positions[issue] for issue in artifact.coverage if issue in issue_positions)
        for artifact in artifacts
    )
    states: dict[int, tuple[int, ...]] = {0: ()}
    bounded = False
    for index, artifact_mask in enumerate(masks):
        additions: dict[int, tuple[int, ...]] = {}
        for covered_mask, selected in tuple(states.items()):
            combined_mask = covered_mask | artifact_mask
            if combined_mask == covered_mask:
                continue
            candidate = (*selected, index)
            current = additions.get(combined_mask) or states.get(combined_mask)
            if current is None or _selection_key(candidate, artifacts, requested) < _selection_key(
                current,
                artifacts,
                requested,
            ):
                additions[combined_mask] = candidate
        for mask, selected in additions.items():
            current = states.get(mask)
            if current is None or _selection_key(selected, artifacts, requested) < _selection_key(
                current,
                artifacts,
                requested,
            ):
                states[mask] = selected
        if len(states) > _MAX_PLANNER_STATES:
            bounded = True
            break

    if not bounded and full_mask in states:
        chosen = states[full_mask]
    elif bounded:
        chosen = _greedy_bounded_selection(full_mask, masks, artifacts, requested)
    else:
        best_mask, chosen = min(
            states.items(),
            key=lambda item: (
                len(requested) - item[0].bit_count(),
                _selection_key(item[1], artifacts, requested),
            ),
        )
        del best_mask
    return tuple(sorted((artifacts[index] for index in chosen), key=_artifact_order_key))


def _greedy_bounded_selection(
    full_mask: int,
    masks: tuple[int, ...],
    artifacts: tuple[DirectArtifactOption, ...],
    requested: frozenset[str],
) -> tuple[int, ...]:
    """Bound pathological state growth without response-order nondeterminism."""
    selected: tuple[int, ...] = ()
    covered = 0
    remaining = set(range(len(artifacts)))
    while covered != full_mask:
        candidates = [index for index in remaining if (masks[index] & ~covered).bit_count()]
        if not candidates:
            break
        best = min(
            candidates,
            key=lambda index: (
                -(masks[index] & ~covered).bit_count(),
                _selection_key((*selected, index), artifacts, requested),
            ),
        )
        selected = (*selected, best)
        covered |= masks[best]
        remaining.remove(best)
    return selected


def _selection_key(
    selected: tuple[int, ...],
    artifacts: tuple[DirectArtifactOption, ...],
    requested: frozenset[str],
) -> _SelectionKey:
    options = tuple(artifacts[index] for index in selected)
    if not options:
        return (0, 0, 0, 0, 0, 0, 0, 0.0, 0, ())
    expected_size = sum(
        item.expected_size if item.expected_size is not None else 2**63 for item in options
    )
    extra_coverage = sum(len(item.coverage - requested) for item in options)
    return (
        max(item.semantic_rank for item in options),
        sum(item.semantic_rank for item in options),
        max(item.quality_rank for item in options),
        sum(item.quality_rank for item in options),
        len(options),
        extra_coverage,
        expected_size,
        -sum(item.provider_confidence for item in options),
        sum(item.provider_priority for item in options),
        tuple(sorted(item.artifact_identity for item in options)),
    )


def _route_order_key(route: DirectRouteOption) -> tuple[object, ...]:
    account_rank = {
        DirectHostAccountState.HEALTHY: 0,
        DirectHostAccountState.NOT_CONFIGURED: 0,
        DirectHostAccountState.UNKNOWN: 1,
        DirectHostAccountState.QUOTA_LIMITED: 2,
        DirectHostAccountState.AUTHENTICATION_REQUIRED: 3,
        DirectHostAccountState.UNAVAILABLE: 4,
    }
    return (
        not route.eligible,
        route.transport_rank,
        route.host_preference,
        account_rank[route.account_state],
        -(route.quota_remaining or 0),
        not route.resumable,
        route.resolver_required,
        route.route_identity,
    )


def _artifact_order_key(artifact: DirectArtifactOption) -> tuple[object, ...]:
    return (
        artifact.semantic_rank,
        artifact.quality_rank,
        artifact.provider_priority,
        artifact.provider_identity,
        artifact.provider_candidate_id,
        artifact.artifact_identity,
    )


def _validate_inputs(
    requested: frozenset[str],
    artifacts: Sequence[DirectArtifactOption],
) -> None:
    if any(not value or len(value) > 100 for value in requested):
        raise ValidationError("Requested coverage identifiers are invalid.")
    artifact_ids: set[str] = set()
    route_ids: set[str] = set()
    for artifact in artifacts:
        if artifact.artifact_identity in artifact_ids:
            raise ValidationError("Direct artifact identities must be unique.")
        artifact_ids.add(artifact.artifact_identity)
        if artifact.semantic_rank < 0 or artifact.quality_rank < 0:
            raise ValidationError("Direct artifact ranks cannot be negative.")
        if not 0 <= artifact.provider_confidence <= 1:
            raise ValidationError("Direct provider confidence must be between zero and one.")
        for route in artifact.routes:
            if route.route_identity in route_ids:
                raise ValidationError("Direct route identities must be unique.")
            route_ids.add(route.route_identity)
            if route.transport_rank < 0 or route.host_preference < 0:
                raise ValidationError("Direct route ranks cannot be negative.")
