"""Deterministic state and progress rules for direct acquisition attempts."""

from __future__ import annotations

import enum
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pullbox.core.exceptions import ValidationError
from pullbox.models.direct_acquisition import (
    DirectAcquisitionAttempt,
    DirectAcquisitionState,
    DirectArtifactAttempt,
    DirectArtifactState,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

ACQUISITION_TRANSITIONS: dict[DirectAcquisitionState, frozenset[DirectAcquisitionState]] = {
    DirectAcquisitionState.DISCOVERED: frozenset(
        {
            DirectAcquisitionState.PLANNED,
            DirectAcquisitionState.INTERVENTION,
            DirectAcquisitionState.CANCELLED,
            DirectAcquisitionState.FAILED,
        }
    ),
    DirectAcquisitionState.PLANNED: frozenset(
        {
            DirectAcquisitionState.QUEUED,
            DirectAcquisitionState.RESOLVING,
            DirectAcquisitionState.CANCELLED,
            DirectAcquisitionState.FAILED,
        }
    ),
    DirectAcquisitionState.QUEUED: frozenset(
        {
            DirectAcquisitionState.RESOLVING,
            DirectAcquisitionState.CANCELLED,
            DirectAcquisitionState.FAILED,
        }
    ),
    DirectAcquisitionState.RESOLVING: frozenset(
        {
            DirectAcquisitionState.DOWNLOADING,
            DirectAcquisitionState.RETRY_PENDING,
            DirectAcquisitionState.INTERVENTION,
            DirectAcquisitionState.CANCELLED,
            DirectAcquisitionState.FAILED,
        }
    ),
    DirectAcquisitionState.DOWNLOADING: frozenset(
        {
            DirectAcquisitionState.PAUSED,
            DirectAcquisitionState.VALIDATING,
            DirectAcquisitionState.RETRY_PENDING,
            DirectAcquisitionState.INTERVENTION,
            DirectAcquisitionState.CANCELLED,
            DirectAcquisitionState.FAILED,
        }
    ),
    DirectAcquisitionState.PAUSED: frozenset(
        {
            DirectAcquisitionState.DOWNLOADING,
            DirectAcquisitionState.CANCELLED,
            DirectAcquisitionState.FAILED,
        }
    ),
    DirectAcquisitionState.VALIDATING: frozenset(
        {
            DirectAcquisitionState.POST_PROCESSING,
            DirectAcquisitionState.RETRY_PENDING,
            DirectAcquisitionState.INTERVENTION,
            DirectAcquisitionState.CANCELLED,
            DirectAcquisitionState.FAILED,
        }
    ),
    DirectAcquisitionState.POST_PROCESSING: frozenset(
        {
            DirectAcquisitionState.COMPLETED,
            DirectAcquisitionState.INTERVENTION,
            DirectAcquisitionState.FAILED,
        }
    ),
    DirectAcquisitionState.RETRY_PENDING: frozenset(
        {
            DirectAcquisitionState.RESOLVING,
            DirectAcquisitionState.CANCELLED,
            DirectAcquisitionState.FAILED,
        }
    ),
    DirectAcquisitionState.INTERVENTION: frozenset(
        {
            DirectAcquisitionState.RESOLVING,
            DirectAcquisitionState.CANCELLED,
            DirectAcquisitionState.FAILED,
        }
    ),
    DirectAcquisitionState.COMPLETED: frozenset(),
    DirectAcquisitionState.CANCELLED: frozenset(),
    DirectAcquisitionState.FAILED: frozenset(),
}

ARTIFACT_TRANSITIONS: dict[DirectArtifactState, frozenset[DirectArtifactState]] = {
    DirectArtifactState.PLANNED: frozenset(
        {
            DirectArtifactState.RESOLVING,
            DirectArtifactState.CANCELLED,
            DirectArtifactState.FAILED,
        }
    ),
    DirectArtifactState.RESOLVING: frozenset(
        {
            DirectArtifactState.TRANSFERRING,
            DirectArtifactState.RETRY_PENDING,
            DirectArtifactState.INTERVENTION,
            DirectArtifactState.CANCELLED,
            DirectArtifactState.FAILED,
        }
    ),
    DirectArtifactState.TRANSFERRING: frozenset(
        {
            DirectArtifactState.PAUSED,
            DirectArtifactState.VALIDATING,
            DirectArtifactState.RETRY_PENDING,
            DirectArtifactState.INTERVENTION,
            DirectArtifactState.CANCELLED,
            DirectArtifactState.FAILED,
        }
    ),
    DirectArtifactState.PAUSED: frozenset(
        {
            DirectArtifactState.TRANSFERRING,
            DirectArtifactState.CANCELLED,
            DirectArtifactState.FAILED,
        }
    ),
    DirectArtifactState.VALIDATING: frozenset(
        {
            DirectArtifactState.COMPLETED,
            DirectArtifactState.INTERVENTION,
            DirectArtifactState.FAILED,
        }
    ),
    DirectArtifactState.RETRY_PENDING: frozenset(
        {
            DirectArtifactState.RESOLVING,
            DirectArtifactState.CANCELLED,
            DirectArtifactState.FAILED,
        }
    ),
    DirectArtifactState.INTERVENTION: frozenset(
        {
            DirectArtifactState.RESOLVING,
            DirectArtifactState.CANCELLED,
            DirectArtifactState.FAILED,
        }
    ),
    DirectArtifactState.COMPLETED: frozenset(),
    DirectArtifactState.CANCELLED: frozenset(),
    DirectArtifactState.FAILED: frozenset(),
}

_ACQUISITION_TERMINAL_STATES = frozenset(
    {
        DirectAcquisitionState.COMPLETED,
        DirectAcquisitionState.CANCELLED,
        DirectAcquisitionState.FAILED,
    }
)
_ARTIFACT_TERMINAL_STATES = frozenset(
    {
        DirectArtifactState.COMPLETED,
        DirectArtifactState.CANCELLED,
        DirectArtifactState.FAILED,
    }
)


def transition_acquisition(
    attempt: DirectAcquisitionAttempt,
    new_state: DirectAcquisitionState,
    *,
    at: datetime | None = None,
) -> bool:
    """Apply one valid acquisition transition, returning whether state changed."""
    current = DirectAcquisitionState(attempt.state)
    if current is new_state:
        return False
    _validate_transition(
        kind="acquisition",
        current=current,
        new_state=new_state,
        allowed=ACQUISITION_TRANSITIONS[current],
    )

    timestamp = at or datetime.now(UTC)
    attempt.state = new_state
    if new_state is DirectAcquisitionState.RESOLVING and attempt.started_at is None:
        attempt.started_at = timestamp
    if new_state is DirectAcquisitionState.CANCELLED:
        attempt.cancelled_at = timestamp
    if new_state in _ACQUISITION_TERMINAL_STATES:
        attempt.completed_at = timestamp
    return True


def transition_artifact(
    artifact: DirectArtifactAttempt,
    new_state: DirectArtifactState,
    *,
    at: datetime | None = None,
) -> bool:
    """Apply one valid artifact transition, returning whether state changed."""
    current = DirectArtifactState(artifact.state)
    if current is new_state:
        return False
    _validate_transition(
        kind="artifact",
        current=current,
        new_state=new_state,
        allowed=ARTIFACT_TRANSITIONS[current],
    )

    artifact.state = new_state
    if new_state in _ARTIFACT_TERMINAL_STATES:
        artifact.completed_at = at or datetime.now(UTC)
    return True


def advance_acquisition_progress(
    attempt: DirectAcquisitionAttempt,
    *,
    revision: int,
    snapshot: Mapping[str, object],
) -> bool:
    """Persist a strictly newer progress snapshot or accept an exact replay."""
    current_revision = attempt.progress_revision
    proposed_snapshot = dict(snapshot)
    if revision == current_revision:
        if proposed_snapshot == attempt.progress_snapshot:
            return False
        raise ValidationError(f"Progress revision {revision} already has different data.")
    if revision < current_revision:
        raise ValidationError(f"Progress revision must be greater than {current_revision}.")

    attempt.progress_revision = revision
    attempt.progress_snapshot = proposed_snapshot
    return True


def _validate_transition[StateT: enum.StrEnum](
    *,
    kind: str,
    current: StateT,
    new_state: StateT,
    allowed: frozenset[StateT],
) -> None:
    if new_state in allowed:
        return
    allowed_text = ", ".join(sorted(state.value for state in allowed)) or "none"
    raise ValidationError(
        f"Invalid direct {kind} transition from {current.value} to "
        f"{new_state.value}. Allowed: {allowed_text}."
    )
