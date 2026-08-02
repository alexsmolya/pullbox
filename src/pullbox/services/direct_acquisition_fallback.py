"""Route-scoped fallback selection for direct acquisition failures."""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select

from pullbox.core.config_resolver import load_system_config_values, parse_bool
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
from pullbox.services.direct_acquisition_state import (
    advance_acquisition_progress,
    transition_acquisition,
    transition_artifact,
)
from pullbox.services.direct_download_history_adapter import (
    ensure_direct_download_history,
    sync_direct_download_history,
)

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession


_ROUTE_SCOPED_FAILURES = frozenset(
    {
        DirectArtifactFailureClass.TRANSIENT_HOST,
        DirectArtifactFailureClass.PERMANENT_MIRROR,
        DirectArtifactFailureClass.UNSUPPORTED_ARTIFACT_HOST,
        DirectArtifactFailureClass.ARTIFACT_HOST_AUTH_REQUIRED,
        DirectArtifactFailureClass.ARTIFACT_HOST_CHALLENGE,
        DirectArtifactFailureClass.HOST_QUOTA,
        DirectArtifactFailureClass.RESOLVER,
        DirectArtifactFailureClass.UNSAFE_ROUTE,
    }
)
_PERSISTENT_ROUTE_FAILURES = frozenset(
    {
        DirectArtifactFailureClass.PERMANENT_MIRROR,
        DirectArtifactFailureClass.UNSUPPORTED_ARTIFACT_HOST,
        DirectArtifactFailureClass.UNSAFE_ROUTE,
    }
)
_AUTO_BLOCKLIST_CONFIG_KEY = "blocklist.auto_add_on_failure"

logger = structlog.get_logger(__name__)


def supports_route_fallback(failure_class: DirectArtifactFailureClass) -> bool:
    """Return whether another ranked route can reasonably avoid this failure."""
    return failure_class in _ROUTE_SCOPED_FAILURES


async def queue_next_artifact_route(
    session: AsyncSession,
    attempt: DirectAcquisitionAttempt,
    failed_artifact: DirectArtifactAttempt,
    *,
    at: datetime,
) -> DirectArtifactAttempt | None:
    """Block one failed route and queue the next untried eligible route."""
    snapshot = deepcopy(attempt.plan_snapshot or {})
    raw_artifacts = snapshot.get("artifacts")
    if not isinstance(raw_artifacts, list):
        return None

    await _auto_blocklist_failed_route(session, attempt, failed_artifact, at=at)
    attempted = {artifact.artifact_identity for artifact in attempt.artifact_attempts}
    route_identities = {
        identity
        for raw_route in raw_artifacts
        if isinstance(raw_route, dict)
        and isinstance((identity := raw_route.get("artifact_identity")), str)
    }
    blocked = await BlocklistService.get_blocked_direct_artifact_routes(
        session,
        route_identities,
    )
    failed_fallback_identity = _route_fallback_identity(
        raw_artifacts,
        failed_artifact.artifact_identity,
    )
    if failed_fallback_identity is None:
        return None
    next_route: dict[str, object] | None = None
    for raw_route in raw_artifacts:
        if not isinstance(raw_route, dict) or raw_route.get("eligible") is not True:
            continue
        if _snapshot_fallback_identity(raw_route) != failed_fallback_identity:
            continue
        identity = raw_route.get("artifact_identity")
        if isinstance(identity, str) and identity not in attempted and identity not in blocked:
            next_route = raw_route
            break
    if next_route is None:
        return None

    identity = next_route.get("artifact_identity")
    host_value = next_route.get("host_kind")
    route_value = next_route.get("route_kind")
    failure_class = failed_artifact.failure_class
    failure_code = failed_artifact.failure_code
    if (
        not isinstance(identity, str)
        or not isinstance(host_value, str)
        or not isinstance(route_value, str)
        or failure_class is None
        or not isinstance(failure_code, str)
    ):
        return None
    try:
        host_kind = DirectArtifactHostKind(host_value)
        route_kind = DirectArtifactRouteKind(route_value)
    except ValueError:
        return None
    if route_kind is not DirectArtifactRouteKind.DIRECT:
        return None

    transition_artifact(failed_artifact, DirectArtifactState.FAILED, at=at)
    failed_artifact.is_selected = False
    failed_artifact.next_retry_at = None

    expected_size = next_route.get("expected_size")
    fallback = DirectArtifactAttempt(
        sequence_no=max(artifact.sequence_no for artifact in attempt.artifact_attempts) + 1,
        artifact_identity=identity,
        route_kind=route_kind,
        host_kind=host_kind,
        state=DirectArtifactState.PLANNED,
        is_selected=True,
        expected_size=expected_size if isinstance(expected_size, int) else None,
    )
    attempt.artifact_attempts.append(fallback)

    for raw_route in raw_artifacts:
        if (
            isinstance(raw_route, dict)
            and raw_route.get("artifact_identity") == failed_artifact.artifact_identity
        ):
            raw_route["eligible"] = False
            raw_route["eligibility_code"] = "route_failed"
            break
    failures = snapshot.get("route_failures")
    route_failures = list(failures) if isinstance(failures, list) else []
    route_failures.append(
        {
            "artifact_identity": failed_artifact.artifact_identity,
            "failure_class": failure_class.value,
            "failure_code": failure_code,
            "host_kind": failed_artifact.host_kind.value,
            "sequence_no": failed_artifact.sequence_no,
        }
    )
    snapshot["route_failures"] = route_failures
    snapshot["selected_artifact_identity"] = identity
    record_acquisition_plan(
        attempt,
        revision=attempt.plan_revision + 1,
        snapshot=snapshot,
    )

    transition_acquisition(attempt, DirectAcquisitionState.QUEUED, at=at)
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
            "stage": "fallback_queued",
            "artifact_attempt_id": fallback.id,
            "host_kind": fallback.host_kind.value,
            "previous_artifact_attempt_id": failed_artifact.id,
            "previous_failure_code": failed_artifact.failure_code,
        },
    )
    await sync_direct_download_history(session, attempt, fallback, at=at)
    await session.commit()
    logger.info(
        "direct_artifact_fallback_queued",
        acquisition_id=attempt.id,
        failed_artifact_id=failed_artifact.id,
        failed_host=failed_artifact.host_kind.value,
        failure_code=failed_artifact.failure_code,
        fallback_artifact_id=fallback.id,
        fallback_host=fallback.host_kind.value,
    )
    return fallback


def _route_fallback_identity(
    routes: list[object],
    route_identity: str,
) -> str | None:
    for route in routes:
        if not isinstance(route, dict) or route.get("artifact_identity") != route_identity:
            continue
        return _snapshot_fallback_identity(route)
    return None


def _snapshot_fallback_identity(route: dict[str, object]) -> str | None:
    fallback_identity = route.get("fallback_identity")
    if isinstance(fallback_identity, str):
        return fallback_identity
    content_identity = route.get("content_identity")
    return content_identity if isinstance(content_identity, str) else None


async def _auto_blocklist_failed_route(
    session: AsyncSession,
    attempt: DirectAcquisitionAttempt,
    failed_artifact: DirectArtifactAttempt,
    *,
    at: datetime,
) -> None:
    failure_class = failed_artifact.failure_class
    if failure_class not in _PERSISTENT_ROUTE_FAILURES:
        return
    configs = await load_system_config_values(session, (_AUTO_BLOCKLIST_CONFIG_KEY,))
    if not parse_bool(configs.get(_AUTO_BLOCKLIST_CONFIG_KEY)):
        return

    history = await ensure_direct_download_history(session, attempt, failed_artifact, at=at)
    series_id = (
        await session.execute(select(Issue.series_id).where(Issue.id == attempt.issue_id))
    ).scalar_one_or_none()
    display_title = str(
        attempt.candidate_snapshot.get("display_title") or attempt.provider_candidate_id
    )
    host_label = _host_label(failed_artifact.host_kind)
    message = failed_artifact.error_message or "The artifact route failed."
    try:
        async with session.begin_nested():
            await BlocklistService.add_direct_artifact_entry(
                session,
                display_title,
                route_identity=failed_artifact.artifact_identity,
                artifact_host=host_label,
                issue_id=attempt.issue_id,
                series_id=series_id,
                error_message=f"{host_label} artifact failed: {message}",
                download_history_id=history.id,
            )
    except Exception:
        logger.debug(
            "direct_artifact_blocklist_auto_add_skipped",
            acquisition_id=attempt.id,
            artifact_id=failed_artifact.id,
            failure_code=failed_artifact.failure_code,
        )


def _host_label(host_kind: DirectArtifactHostKind) -> str:
    if host_kind is DirectArtifactHostKind.MEGA:
        return "MEGA"
    if host_kind is DirectArtifactHostKind.PIXELDRAIN:
        return "PixelDrain"
    return host_kind.value.replace("_", " ").title()
