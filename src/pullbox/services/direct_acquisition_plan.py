"""Deterministic, redacted plan snapshots for direct acquisition."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pullbox.core.exceptions import ValidationError

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from pullbox.models.direct_acquisition import (
        DirectAcquisitionAttempt,
        DirectArtifactHostKind,
        DirectArtifactRouteKind,
        DirectHostAccountState,
        DirectProviderState,
    )


_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,499}\Z")
_REASON_CODE = re.compile(r"[a-z][a-z0-9_]{0,99}\Z")


@dataclass(frozen=True, slots=True)
class ArtifactPlanSnapshotInput:
    """Non-sensitive planner output persisted for one artifact option."""

    artifact_identity: str
    content_rank: int
    transport_rank: int
    route_kind: DirectArtifactRouteKind
    host_kind: DirectArtifactHostKind
    eligible: bool
    eligibility_code: str
    host_preference: int
    account_state: DirectHostAccountState
    provider_priority: int
    quota_remaining: int | None
    range_supported: bool
    resolver_required: bool
    expected_size: int | None


def build_plan_snapshot(
    *,
    provider_identity: str,
    provider_candidate_id: str,
    selected_artifact_identity: str,
    provider_state: DirectProviderState,
    artifacts: Sequence[ArtifactPlanSnapshotInput],
) -> dict[str, object]:
    """Build stable persistence data from already-ranked planner output."""
    _validate_identity("provider identity", provider_identity)
    _validate_identity("provider candidate identity", provider_candidate_id)
    if not artifacts:
        raise ValidationError("A direct acquisition plan requires at least one artifact.")

    identities: set[str] = set()
    for artifact in artifacts:
        _validate_artifact(artifact)
        if artifact.artifact_identity in identities:
            raise ValidationError("Artifact identities must be unique within a plan.")
        identities.add(artifact.artifact_identity)

    selected = next(
        (
            artifact
            for artifact in artifacts
            if artifact.artifact_identity == selected_artifact_identity
        ),
        None,
    )
    if selected is None:
        raise ValidationError("The selected artifact is not present in the plan.")
    if not selected.eligible:
        raise ValidationError("The selected artifact must be eligible for transfer.")

    ordered = sorted(
        artifacts,
        key=lambda artifact: (
            artifact.content_rank,
            artifact.transport_rank,
            artifact.host_preference,
            artifact.provider_priority,
            artifact.artifact_identity,
        ),
    )
    return {
        "schema_version": 1,
        "provider_identity": provider_identity,
        "provider_candidate_id": provider_candidate_id,
        "provider_state": provider_state.value,
        "selected_artifact_identity": selected_artifact_identity,
        "artifacts": [_serialize_artifact(artifact) for artifact in ordered],
    }


def record_acquisition_plan(
    attempt: DirectAcquisitionAttempt,
    *,
    revision: int,
    snapshot: Mapping[str, object],
) -> bool:
    """Record a newer detached plan, or accept an exact same-revision replay."""
    if revision < 1:
        raise ValidationError("Plan revision must be at least 1.")

    proposed = _json_copy(snapshot)
    current_revision = attempt.plan_revision or 0
    current = _json_copy(attempt.plan_snapshot or {})
    if revision == current_revision:
        if proposed == current:
            return False
        raise ValidationError(f"Plan revision {revision} already has different data.")
    if revision < current_revision:
        raise ValidationError(f"Plan revision must be greater than {current_revision}.")

    attempt.plan_revision = revision
    attempt.plan_snapshot = proposed
    return True


def _validate_artifact(artifact: ArtifactPlanSnapshotInput) -> None:
    _validate_identity("artifact identity", artifact.artifact_identity)
    if not _REASON_CODE.fullmatch(artifact.eligibility_code):
        raise ValidationError("Invalid artifact eligibility code.")
    for label, value in (
        ("content rank", artifact.content_rank),
        ("transport rank", artifact.transport_rank),
        ("host preference", artifact.host_preference),
        ("provider priority", artifact.provider_priority),
    ):
        if value < 0:
            raise ValidationError(f"Artifact {label} cannot be negative.")
    if artifact.quota_remaining is not None and artifact.quota_remaining < 0:
        raise ValidationError("Artifact quota remaining cannot be negative.")
    if artifact.expected_size is not None and artifact.expected_size < 0:
        raise ValidationError("Artifact expected size cannot be negative.")


def _validate_identity(label: str, value: str) -> None:
    if not _IDENTITY.fullmatch(value):
        raise ValidationError(f"Invalid {label}; URLs and query strings are not allowed.")


def _serialize_artifact(artifact: ArtifactPlanSnapshotInput) -> dict[str, object]:
    return {
        "artifact_identity": artifact.artifact_identity,
        "content_rank": artifact.content_rank,
        "transport_rank": artifact.transport_rank,
        "route_kind": artifact.route_kind.value,
        "host_kind": artifact.host_kind.value,
        "eligible": artifact.eligible,
        "eligibility_code": artifact.eligibility_code,
        "host_preference": artifact.host_preference,
        "account_state": artifact.account_state.value,
        "provider_priority": artifact.provider_priority,
        "quota_remaining": artifact.quota_remaining,
        "range_supported": artifact.range_supported,
        "resolver_required": artifact.resolver_required,
        "expected_size": artifact.expected_size,
    }


def _json_copy(value: Mapping[str, object]) -> dict[str, object]:
    try:
        serialized = json.dumps(
            value,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        result = json.loads(serialized)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Direct acquisition plans must contain valid JSON data.") from exc
    if not isinstance(result, dict):
        raise ValidationError("Direct acquisition plan snapshots must be JSON objects.")
    return result
