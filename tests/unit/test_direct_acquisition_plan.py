"""Deterministic durable-plan contracts for direct acquisition."""

from __future__ import annotations

import random

import pytest

from pullbox.core.exceptions import ValidationError
from pullbox.models.direct_acquisition import (
    DirectAcquisitionAttempt,
    DirectAcquisitionState,
    DirectArtifactHostKind,
    DirectArtifactRouteKind,
    DirectHostAccountState,
    DirectProviderState,
)
from pullbox.services.direct_acquisition_plan import (
    ArtifactPlanSnapshotInput,
    build_plan_snapshot,
    record_acquisition_plan,
)


def _attempt() -> DirectAcquisitionAttempt:
    return DirectAcquisitionAttempt(
        request_key="manual:issue:1:plan-test",
        issue_id=1,
        provider_identity="community.getcomics",
        provider_candidate_id="candidate-1",
        state=DirectAcquisitionState.DISCOVERED,
        plan_revision=0,
        plan_snapshot={},
    )


def _artifacts() -> list[ArtifactPlanSnapshotInput]:
    return [
        ArtifactPlanSnapshotInput(
            artifact_identity="artifact-pixeldrain",
            content_rank=0,
            transport_rank=1,
            route_kind=DirectArtifactRouteKind.DIRECT,
            host_kind=DirectArtifactHostKind.PIXELDRAIN,
            eligible=True,
            eligibility_code="eligible",
            host_preference=10,
            account_state=DirectHostAccountState.HEALTHY,
            provider_priority=20,
            quota_remaining=1_000_000_000,
            range_supported=True,
            resolver_required=False,
            expected_size=200_000_000,
        ),
        ArtifactPlanSnapshotInput(
            artifact_identity="artifact-generic",
            content_rank=0,
            transport_rank=0,
            route_kind=DirectArtifactRouteKind.DIRECT,
            host_kind=DirectArtifactHostKind.GENERIC_HTTPS,
            eligible=True,
            eligibility_code="eligible",
            host_preference=50,
            account_state=DirectHostAccountState.NOT_CONFIGURED,
            provider_priority=20,
            quota_remaining=None,
            range_supported=True,
            resolver_required=False,
            expected_size=200_000_000,
        ),
        ArtifactPlanSnapshotInput(
            artifact_identity="artifact-terabox",
            content_rank=0,
            transport_rank=3,
            route_kind=DirectArtifactRouteKind.DIRECT,
            host_kind=DirectArtifactHostKind.TERABOX,
            eligible=False,
            eligibility_code="authentication_required",
            host_preference=30,
            account_state=DirectHostAccountState.AUTHENTICATION_REQUIRED,
            provider_priority=20,
            quota_remaining=None,
            range_supported=False,
            resolver_required=True,
            expected_size=200_000_000,
        ),
    ]


def test_plan_snapshot_is_deterministic_under_shuffled_artifacts() -> None:
    artifacts = _artifacts()
    shuffled = artifacts.copy()
    random.Random(20260727).shuffle(shuffled)

    expected = build_plan_snapshot(
        provider_identity="community.getcomics",
        provider_candidate_id="candidate-1",
        selected_artifact_identity="artifact-generic",
        provider_state=DirectProviderState.HEALTHY,
        artifacts=artifacts,
    )
    actual = build_plan_snapshot(
        provider_identity="community.getcomics",
        provider_candidate_id="candidate-1",
        selected_artifact_identity="artifact-generic",
        provider_state=DirectProviderState.HEALTHY,
        artifacts=shuffled,
    )

    assert actual == expected
    assert [item["artifact_identity"] for item in actual["artifacts"]] == [
        "artifact-generic",
        "artifact-pixeldrain",
        "artifact-terabox",
    ]


def test_plan_snapshot_contains_only_redacted_ranking_inputs() -> None:
    snapshot = build_plan_snapshot(
        provider_identity="community.getcomics",
        provider_candidate_id="candidate-1",
        selected_artifact_identity="artifact-generic",
        provider_state=DirectProviderState.HEALTHY,
        artifacts=_artifacts(),
    )
    rendered = repr(snapshot)

    assert snapshot["schema_version"] == 1
    assert snapshot["provider_state"] == "healthy"
    assert "url" not in rendered.lower()
    assert "token" not in rendered.lower()
    assert "cookie" not in rendered.lower()
    assert "authorization" not in rendered.lower()


def test_plan_snapshot_requires_selected_eligible_artifact() -> None:
    with pytest.raises(ValidationError, match="selected artifact must be eligible"):
        build_plan_snapshot(
            provider_identity="community.getcomics",
            provider_candidate_id="candidate-1",
            selected_artifact_identity="artifact-terabox",
            provider_state=DirectProviderState.HEALTHY,
            artifacts=_artifacts(),
        )


@pytest.mark.parametrize(
    "artifact_identity",
    [
        "https://files.example.test/download?token=secret",
        "artifact?token=secret",
        "artifact/../../secret",
    ],
)
def test_plan_snapshot_rejects_identifiers_that_could_persist_signed_urls(
    artifact_identity: str,
) -> None:
    artifact = _artifacts()[0]
    unsafe = ArtifactPlanSnapshotInput(
        artifact_identity=artifact_identity,
        content_rank=artifact.content_rank,
        transport_rank=artifact.transport_rank,
        route_kind=artifact.route_kind,
        host_kind=artifact.host_kind,
        eligible=artifact.eligible,
        eligibility_code=artifact.eligibility_code,
        host_preference=artifact.host_preference,
        account_state=artifact.account_state,
        provider_priority=artifact.provider_priority,
        quota_remaining=artifact.quota_remaining,
        range_supported=artifact.range_supported,
        resolver_required=artifact.resolver_required,
        expected_size=artifact.expected_size,
    )

    with pytest.raises(ValidationError, match="artifact identity"):
        build_plan_snapshot(
            provider_identity="community.getcomics",
            provider_candidate_id="candidate-1",
            selected_artifact_identity=artifact_identity,
            provider_state=DirectProviderState.HEALTHY,
            artifacts=[unsafe],
        )


def test_recorded_plan_is_detached_and_same_revision_is_immutable() -> None:
    attempt = _attempt()
    snapshot = build_plan_snapshot(
        provider_identity="community.getcomics",
        provider_candidate_id="candidate-1",
        selected_artifact_identity="artifact-generic",
        provider_state=DirectProviderState.HEALTHY,
        artifacts=_artifacts(),
    )

    assert record_acquisition_plan(attempt, revision=1, snapshot=snapshot) is True
    snapshot["provider_state"] = "unavailable"
    assert attempt.plan_snapshot["provider_state"] == "healthy"

    replay = build_plan_snapshot(
        provider_identity="community.getcomics",
        provider_candidate_id="candidate-1",
        selected_artifact_identity="artifact-generic",
        provider_state=DirectProviderState.HEALTHY,
        artifacts=_artifacts(),
    )
    assert record_acquisition_plan(attempt, revision=1, snapshot=replay) is False

    changed = dict(replay)
    changed["provider_state"] = "degraded"
    with pytest.raises(ValidationError, match="already has different data"):
        record_acquisition_plan(attempt, revision=1, snapshot=changed)


def test_explicit_new_plan_revision_can_capture_a_fallback_decision() -> None:
    attempt = _attempt()
    first = build_plan_snapshot(
        provider_identity="community.getcomics",
        provider_candidate_id="candidate-1",
        selected_artifact_identity="artifact-generic",
        provider_state=DirectProviderState.HEALTHY,
        artifacts=_artifacts(),
    )
    record_acquisition_plan(attempt, revision=1, snapshot=first)

    fallback = build_plan_snapshot(
        provider_identity="community.getcomics",
        provider_candidate_id="candidate-1",
        selected_artifact_identity="artifact-pixeldrain",
        provider_state=DirectProviderState.DEGRADED,
        artifacts=_artifacts(),
    )

    assert record_acquisition_plan(attempt, revision=2, snapshot=fallback) is True
    assert attempt.plan_revision == 2
    assert attempt.plan_snapshot["selected_artifact_identity"] == "artifact-pixeldrain"
