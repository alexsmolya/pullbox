"""State-machine tests for direct acquisition and artifact attempts."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from pullbox.core.exceptions import ValidationError
from pullbox.models.direct_acquisition import (
    DirectAcquisitionAttempt,
    DirectAcquisitionState,
    DirectArtifactAttempt,
    DirectArtifactHostKind,
    DirectArtifactRouteKind,
    DirectArtifactState,
)
from pullbox.services.direct_acquisition_state import (
    advance_acquisition_progress,
    transition_acquisition,
    transition_artifact,
)

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


def _acquisition(state: DirectAcquisitionState) -> DirectAcquisitionAttempt:
    return DirectAcquisitionAttempt(
        request_key="manual:issue:1:state-test",
        issue_id=1,
        provider_identity="synthetic",
        provider_candidate_id="candidate-1",
        state=state,
        progress_revision=0,
        progress_snapshot={},
    )


def _artifact(state: DirectArtifactState) -> DirectArtifactAttempt:
    return DirectArtifactAttempt(
        acquisition_attempt_id=1,
        sequence_no=0,
        artifact_identity="artifact-1",
        route_kind=DirectArtifactRouteKind.DIRECT,
        host_kind=DirectArtifactHostKind.GENERIC_HTTPS,
        state=state,
    )


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (DirectAcquisitionState.DISCOVERED, DirectAcquisitionState.PLANNED),
        (DirectAcquisitionState.PLANNED, DirectAcquisitionState.QUEUED),
        (DirectAcquisitionState.QUEUED, DirectAcquisitionState.RESOLVING),
        (DirectAcquisitionState.RESOLVING, DirectAcquisitionState.DOWNLOADING),
        (DirectAcquisitionState.RESOLVING, DirectAcquisitionState.QUEUED),
        (DirectAcquisitionState.DOWNLOADING, DirectAcquisitionState.PAUSED),
        (DirectAcquisitionState.DOWNLOADING, DirectAcquisitionState.QUEUED),
        (DirectAcquisitionState.PAUSED, DirectAcquisitionState.DOWNLOADING),
        (DirectAcquisitionState.DOWNLOADING, DirectAcquisitionState.VALIDATING),
        (DirectAcquisitionState.VALIDATING, DirectAcquisitionState.QUEUED),
        (DirectAcquisitionState.VALIDATING, DirectAcquisitionState.POST_PROCESSING),
        (DirectAcquisitionState.POST_PROCESSING, DirectAcquisitionState.COMPLETED),
        (DirectAcquisitionState.RESOLVING, DirectAcquisitionState.RETRY_PENDING),
        (DirectAcquisitionState.RETRY_PENDING, DirectAcquisitionState.RESOLVING),
        (DirectAcquisitionState.RETRY_PENDING, DirectAcquisitionState.QUEUED),
        (DirectAcquisitionState.INTERVENTION, DirectAcquisitionState.RESOLVING),
        (DirectAcquisitionState.INTERVENTION, DirectAcquisitionState.QUEUED),
    ],
)
def test_valid_acquisition_transitions(current, target) -> None:  # type: ignore[no-untyped-def]
    attempt = _acquisition(current)

    changed = transition_acquisition(attempt, target, at=NOW)

    assert changed is True
    assert attempt.state is target


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (DirectArtifactState.PLANNED, DirectArtifactState.RESOLVING),
        (DirectArtifactState.RESOLVING, DirectArtifactState.TRANSFERRING),
        (DirectArtifactState.TRANSFERRING, DirectArtifactState.PAUSED),
        (DirectArtifactState.PAUSED, DirectArtifactState.TRANSFERRING),
        (DirectArtifactState.TRANSFERRING, DirectArtifactState.VALIDATING),
        (DirectArtifactState.VALIDATING, DirectArtifactState.COMPLETED),
        (DirectArtifactState.RESOLVING, DirectArtifactState.RETRY_PENDING),
        (DirectArtifactState.RETRY_PENDING, DirectArtifactState.RESOLVING),
        (DirectArtifactState.INTERVENTION, DirectArtifactState.RESOLVING),
    ],
)
def test_valid_artifact_transitions(current, target) -> None:  # type: ignore[no-untyped-def]
    artifact = _artifact(current)

    changed = transition_artifact(artifact, target, at=NOW)

    assert changed is True
    assert artifact.state is target


def test_same_state_transition_is_idempotent() -> None:
    attempt = _acquisition(DirectAcquisitionState.RESOLVING)

    changed = transition_acquisition(attempt, DirectAcquisitionState.RESOLVING, at=NOW)

    assert changed is False
    assert attempt.started_at is None


@pytest.mark.parametrize(
    "terminal",
    [
        DirectAcquisitionState.COMPLETED,
        DirectAcquisitionState.CANCELLED,
        DirectAcquisitionState.FAILED,
    ],
)
def test_terminal_acquisition_states_reject_further_transitions(terminal) -> None:  # type: ignore[no-untyped-def]
    attempt = _acquisition(terminal)

    with pytest.raises(ValidationError, match="Invalid direct acquisition transition"):
        transition_acquisition(attempt, DirectAcquisitionState.RESOLVING, at=NOW)


def test_invalid_artifact_transition_does_not_mutate_state() -> None:
    artifact = _artifact(DirectArtifactState.PLANNED)

    with pytest.raises(ValidationError, match="Invalid direct artifact transition"):
        transition_artifact(artifact, DirectArtifactState.COMPLETED, at=NOW)

    assert artifact.state is DirectArtifactState.PLANNED
    assert artifact.completed_at is None


def test_acquisition_transition_updates_lifecycle_timestamps() -> None:
    attempt = _acquisition(DirectAcquisitionState.QUEUED)
    transition_acquisition(attempt, DirectAcquisitionState.RESOLVING, at=NOW)
    assert attempt.started_at == NOW

    attempt.state = DirectAcquisitionState.POST_PROCESSING
    transition_acquisition(attempt, DirectAcquisitionState.COMPLETED, at=NOW)
    assert attempt.completed_at == NOW

    cancelled = _acquisition(DirectAcquisitionState.PLANNED)
    transition_acquisition(cancelled, DirectAcquisitionState.CANCELLED, at=NOW)
    assert cancelled.cancelled_at == NOW
    assert cancelled.completed_at == NOW


def test_artifact_completed_transition_sets_completed_timestamp() -> None:
    artifact = _artifact(DirectArtifactState.VALIDATING)

    transition_artifact(artifact, DirectArtifactState.COMPLETED, at=NOW)

    assert artifact.completed_at == NOW


def test_progress_revision_must_advance_monotonically() -> None:
    attempt = _acquisition(DirectAcquisitionState.DOWNLOADING)

    changed = advance_acquisition_progress(
        attempt,
        revision=1,
        snapshot={"bytes_transferred": 512, "progress_pct": 10},
    )

    assert changed is True
    assert attempt.progress_revision == 1
    assert attempt.progress_snapshot == {"bytes_transferred": 512, "progress_pct": 10}

    with pytest.raises(ValidationError, match="must be greater"):
        advance_acquisition_progress(
            attempt,
            revision=0,
            snapshot={"bytes_transferred": 256},
        )

    assert attempt.progress_revision == 1
    assert attempt.progress_snapshot == {"bytes_transferred": 512, "progress_pct": 10}


def test_replayed_identical_progress_revision_is_idempotent() -> None:
    snapshot = {"bytes_transferred": 512, "progress_pct": 10}
    attempt = _acquisition(DirectAcquisitionState.DOWNLOADING)
    attempt.progress_revision = 3
    attempt.progress_snapshot = snapshot.copy()

    assert advance_acquisition_progress(attempt, revision=3, snapshot=snapshot.copy()) is False

    with pytest.raises(ValidationError, match="already has different data"):
        advance_acquisition_progress(
            attempt,
            revision=3,
            snapshot={"bytes_transferred": 1024, "progress_pct": 20},
        )
