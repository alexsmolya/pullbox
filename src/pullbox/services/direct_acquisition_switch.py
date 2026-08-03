"""User-directed switching between verified equivalent artifact routes."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select

from pullbox.models.direct_acquisition import (
    DirectAcquisitionAttempt,
    DirectAcquisitionState,
    DirectArtifactAttempt,
    DirectArtifactFailureClass,
    DirectArtifactHostKind,
    DirectArtifactRouteKind,
    DirectArtifactState,
)
from pullbox.models.issue import Issue
from pullbox.services.blocklist_service import BlocklistService
from pullbox.services.direct_acquisition_plan import record_acquisition_plan
from pullbox.services.direct_acquisition_state import advance_acquisition_progress
from pullbox.services.direct_download_history_adapter import (
    ensure_direct_download_history,
    sync_direct_download_history,
)

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

_MANUALLY_RESELECTABLE_FAILURES = frozenset(
    {
        DirectArtifactFailureClass.TRANSIENT_HOST,
        DirectArtifactFailureClass.ARTIFACT_HOST_AUTH_REQUIRED,
        DirectArtifactFailureClass.ARTIFACT_HOST_CHALLENGE,
        DirectArtifactFailureClass.HOST_QUOTA,
        DirectArtifactFailureClass.RESOLVER,
        DirectArtifactFailureClass.USER_ACTION,
    }
)


class DirectSourceSwitchError(RuntimeError):
    """A source switch cannot be completed from the current durable plan."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class DirectSourceSwitchOption:
    """One available, unblocked route equivalent to the selected artifact."""

    artifact_identity: str
    host_kind: DirectArtifactHostKind
    expected_size: int | None


@dataclass(frozen=True, slots=True)
class DirectSourceSwitchOutcome:
    """Durable result of replacing one selected artifact route."""

    selected: DirectArtifactAttempt
    previous_host: DirectArtifactHostKind
    current_route_blocklisted: bool


async def list_source_switch_options(
    session: AsyncSession,
    attempt: DirectAcquisitionAttempt,
) -> list[DirectSourceSwitchOption]:
    """Return safe alternatives in their existing acquisition-plan order."""
    current = _selected_artifact(attempt)
    routes = _snapshot_routes(attempt)
    fallback_identity = _fallback_identity_for(routes, current.artifact_identity)
    if fallback_identity is None:
        return []

    attempted = {artifact.artifact_identity: artifact for artifact in attempt.artifact_attempts}
    route_identities = {
        identity
        for route in routes
        if isinstance((identity := route.get("artifact_identity")), str)
    }
    blocked = await BlocklistService.get_blocked_direct_artifact_routes(
        session,
        route_identities,
    )
    options: list[DirectSourceSwitchOption] = []
    for route in routes:
        identity = route.get("artifact_identity")
        previous = attempted.get(identity) if isinstance(identity, str) else None
        reselectable = previous is not None and _is_manually_reselectable(previous)
        if (
            not isinstance(identity, str)
            or identity == current.artifact_identity
            or (route.get("eligible") is not True and not reselectable)
            or (previous is not None and not reselectable)
            or identity in blocked
            or _snapshot_fallback_identity(route) != fallback_identity
        ):
            continue
        try:
            route_kind = DirectArtifactRouteKind(str(route.get("route_kind")))
            host_kind = DirectArtifactHostKind(str(route.get("host_kind")))
        except ValueError:
            continue
        if route_kind is not DirectArtifactRouteKind.DIRECT:
            continue
        expected_size = route.get("expected_size")
        options.append(
            DirectSourceSwitchOption(
                artifact_identity=identity,
                host_kind=host_kind,
                expected_size=expected_size if isinstance(expected_size, int) else None,
            )
        )
    return options


async def queue_source_switch(
    session: AsyncSession,
    attempt: DirectAcquisitionAttempt,
    current: DirectArtifactAttempt,
    *,
    target_artifact_identity: str | None,
    block_current: bool,
    discarded_bytes: int | None = None,
    at: datetime,
) -> DirectSourceSwitchOutcome:
    """Replace a cooperatively cancelled route and queue its selected alternative."""
    if attempt.state is not DirectAcquisitionState.CANCELLED:
        raise DirectSourceSwitchError(
            "source_switch_not_cancelled",
            "The current transfer did not stop cleanly, so its source was not changed.",
        )
    if current.state is not DirectArtifactState.CANCELLED or not current.is_selected:
        raise DirectSourceSwitchError(
            "source_switch_artifact_not_cancelled",
            "The current artifact did not stop cleanly, so its source was not changed.",
        )

    options = await list_source_switch_options(session, attempt)
    if target_artifact_identity is None:
        selected_option = options[0] if options else None
    else:
        selected_option = next(
            (option for option in options if option.artifact_identity == target_artifact_identity),
            None,
        )
    if selected_option is None:
        raise DirectSourceSwitchError(
            "source_switch_route_unavailable",
            "The requested replacement source is not available for this download.",
        )

    history = await ensure_direct_download_history(session, attempt, current, at=at)
    if block_current:
        series_id = (
            await session.execute(select(Issue.series_id).where(Issue.id == attempt.issue_id))
        ).scalar_one_or_none()
        display_title = str(
            attempt.candidate_snapshot.get("display_title") or attempt.provider_candidate_id
        )
        await BlocklistService.add_direct_artifact_entry(
            session,
            display_title,
            route_identity=current.artifact_identity,
            artifact_host=direct_source_host_label(current.host_kind),
            issue_id=attempt.issue_id,
            series_id=series_id,
            error_message="This artifact route was skipped by the user while downloading.",
            download_history_id=history.id,
        )

    snapshot = deepcopy(attempt.plan_snapshot or {})
    raw_routes = snapshot.get("artifacts")
    routes = (
        [route for route in raw_routes if isinstance(route, dict)]
        if isinstance(raw_routes, list)
        else []
    )
    for route in routes:
        if route.get("artifact_identity") == current.artifact_identity:
            route["eligible"] = False
            route["eligibility_code"] = "source_switched"
        elif route.get("artifact_identity") == selected_option.artifact_identity:
            route["eligible"] = True
            route["eligibility_code"] = "eligible"

    current.is_selected = False
    current.next_retry_at = None
    current.failure_class = DirectArtifactFailureClass.USER_ACTION
    current.failure_code = "source_switched_by_user"
    current.error_message = "Switched to another source by user."

    replacement = next(
        (
            artifact
            for artifact in attempt.artifact_attempts
            if artifact.artifact_identity == selected_option.artifact_identity
        ),
        None,
    )
    if replacement is None:
        replacement = DirectArtifactAttempt(
            sequence_no=max(artifact.sequence_no for artifact in attempt.artifact_attempts) + 1,
            artifact_identity=selected_option.artifact_identity,
            route_kind=DirectArtifactRouteKind.DIRECT,
            host_kind=selected_option.host_kind,
        )
        attempt.artifact_attempts.append(replacement)
    replacement.state = DirectArtifactState.PLANNED
    replacement.is_selected = True
    replacement.expected_size = selected_option.expected_size
    replacement.bytes_transferred = 0
    replacement.etag = None
    replacement.last_modified_at = None
    replacement.quarantine_path = None
    replacement.retry_count = 0
    replacement.next_retry_at = None
    replacement.failure_class = None
    replacement.failure_code = None
    replacement.error_message = None
    replacement.completed_at = None

    switches = snapshot.get("route_switches")
    route_switches = list(switches) if isinstance(switches, list) else []
    route_switches.append(
        {
            "from_artifact_identity": current.artifact_identity,
            "from_host_kind": current.host_kind.value,
            "to_artifact_identity": replacement.artifact_identity,
            "to_host_kind": replacement.host_kind.value,
            "blocklisted": block_current,
            "sequence_no": current.sequence_no,
        }
    )
    snapshot["route_switches"] = route_switches
    snapshot["selected_artifact_identity"] = replacement.artifact_identity
    snapshot["artifacts"] = routes
    record_acquisition_plan(
        attempt,
        revision=attempt.plan_revision + 1,
        snapshot=snapshot,
    )

    attempt.state = DirectAcquisitionState.QUEUED
    attempt.cancelled_at = None
    attempt.completed_at = None
    attempt.retry_count = 0
    attempt.next_retry_at = None
    attempt.failure_class = None
    attempt.failure_code = None
    attempt.error_message = None
    await session.flush()
    advance_acquisition_progress(
        attempt,
        revision=attempt.progress_revision + 1,
        snapshot={
            "schema_version": 1,
            "stage": "source_switch_queued",
            "artifact_attempt_id": replacement.id,
            "host_kind": replacement.host_kind.value,
            "previous_artifact_attempt_id": current.id,
            "previous_host_kind": current.host_kind.value,
            "previous_bytes_discarded": max(
                0,
                current.bytes_transferred if discarded_bytes is None else discarded_bytes,
            ),
        },
    )
    await sync_direct_download_history(session, attempt, replacement, at=at)
    await session.commit()
    logger.info(
        "direct_artifact_source_switch_queued",
        acquisition_id=attempt.id,
        previous_artifact_id=current.id,
        previous_host=current.host_kind.value,
        replacement_artifact_id=replacement.id,
        replacement_host=replacement.host_kind.value,
        current_route_blocklisted=block_current,
    )
    return DirectSourceSwitchOutcome(
        selected=replacement,
        previous_host=current.host_kind,
        current_route_blocklisted=block_current,
    )


def _selected_artifact(attempt: DirectAcquisitionAttempt) -> DirectArtifactAttempt:
    selected = [artifact for artifact in attempt.artifact_attempts if artifact.is_selected]
    if len(selected) != 1:
        raise DirectSourceSwitchError(
            "source_switch_selection_invalid",
            "This direct download does not have one active artifact source.",
        )
    return selected[0]


def _snapshot_routes(attempt: DirectAcquisitionAttempt) -> list[dict[str, object]]:
    raw_routes = (attempt.plan_snapshot or {}).get("artifacts")
    if not isinstance(raw_routes, list):
        return []
    return [route for route in raw_routes if isinstance(route, dict)]


def _fallback_identity_for(routes: list[dict[str, object]], identity: str) -> str | None:
    for route in routes:
        if route.get("artifact_identity") == identity:
            return _snapshot_fallback_identity(route)
    return None


def _snapshot_fallback_identity(route: dict[str, object]) -> str | None:
    fallback_identity = route.get("fallback_identity")
    if isinstance(fallback_identity, str):
        return fallback_identity
    content_identity = route.get("content_identity")
    return content_identity if isinstance(content_identity, str) else None


def _is_manually_reselectable(artifact: DirectArtifactAttempt) -> bool:
    return (
        artifact.state
        in {
            DirectArtifactState.CANCELLED,
            DirectArtifactState.FAILED,
            DirectArtifactState.INTERVENTION,
        }
        and artifact.failure_class in _MANUALLY_RESELECTABLE_FAILURES
    )


def direct_source_host_label(host_kind: DirectArtifactHostKind) -> str:
    """Return the stable operator-facing label for an artifact host."""
    if host_kind is DirectArtifactHostKind.MEGA:
        return "MEGA"
    if host_kind is DirectArtifactHostKind.PIXELDRAIN:
        return "PixelDrain"
    if host_kind is DirectArtifactHostKind.GENERIC_HTTPS:
        return "HTTPS"
    if host_kind is DirectArtifactHostKind.MEDIAFIRE:
        return "MediaFire"
    if host_kind is DirectArtifactHostKind.TERABOX:
        return "TeraBox"
    if host_kind is DirectArtifactHostKind.DATANODES:
        return "DataNodes"
    return host_kind.value.replace("_", " ").title()
